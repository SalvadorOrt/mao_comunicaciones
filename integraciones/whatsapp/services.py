# integraciones/whatsapp/services.py

import logging
import mimetypes

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone

from comunicaciones.models import (
    Conversacion,
    IdentidadContactoExterna,
    Mensaje,
    NumeroCanal,
)
from comunicaciones.services import (
    actualizar_estado_mensaje,
    crear_conversacion,
    obtener_o_crear_contacto_whatsapp,
    registrar_archivo_multimedia,
    registrar_mensaje_idempotente,
)

from integraciones.whatsapp.client import (
    descargar_archivo_fisico,
    enviar_documento_meta,
    enviar_mensaje_texto_meta,
    obtener_url_descarga_media,
    subir_media_meta,
)


logger = logging.getLogger(__name__)


# ==========================================================
# CONSTANTES
# ==========================================================


PROVEEDOR_IDENTIDAD_META = "META"


# ==========================================================
# EXCEPCIONES
# ==========================================================


class WhatsAppServiceError(Exception):
    """
    Excepción base de la capa de integración WhatsApp.
    """

    pass


class WhatsAppConfiguracionError(
    WhatsAppServiceError
):
    """
    Falta configuración necesaria para operar
    contra WhatsApp Cloud API.
    """

    pass


class WhatsAppEnvioError(
    WhatsAppServiceError
):
    """
    Ocurrió un error enviando contenido mediante Meta.
    """

    pass


# ==========================================================
# RESOLVER CANAL DESDE META
# ==========================================================


def obtener_canal_por_phone_number_id(
    phone_number_id,
):
    """
    Obtiene el NumeroCanal correspondiente al
    phone_number_id recibido desde Meta.

    Esta relación técnica pertenece exclusivamente a
    MAO Comunicaciones.
    """

    phone_number_id = str(
        phone_number_id or ""
    ).strip()

    if not phone_number_id:
        return None

    return (
        NumeroCanal.objects
        .select_related(
            "sucursal",
        )
        .filter(
            proveedor=(
                NumeroCanal
                .Proveedor
                .WHATSAPP
            ),
            identificador_externo=phone_number_id,
            activo=True,
        )
        .first()
    )


# ==========================================================
# PROCESAR EVENTO DEL WEBHOOK
# ==========================================================


def procesar_evento_webhook(
    evento,
):
    """
    Punto de entrada para eventos normalizados
    procedentes del parser de WhatsApp.

    Recibe:

        message
        status

    y los transforma en operaciones internas de
    MAO Comunicaciones.

    NO contiene lógica de:

        - ERP;
        - citas;
        - IA;
        - órdenes de trabajo;
        - reglas empresariales.
    """

    if not isinstance(
        evento,
        dict,
    ):
        raise ValidationError(
            "El evento de WhatsApp no es válido."
        )

    phone_number_id = str(
        evento.get(
            "phone_number_id"
        )
        or ""
    ).strip()

    if not phone_number_id:

        logger.warning(
            "Evento Meta sin phone_number_id."
        )

        return None

    # ======================================================
    # CANAL
    # ======================================================

    canal = obtener_canal_por_phone_number_id(
        phone_number_id
    )

    if canal is None:

        logger.warning(
            (
                "Evento recibido para un "
                "phone_number_id no registrado."
            )
        )

        return None

    tipo_evento = str(
        evento.get(
            "tipo_evento"
        )
        or ""
    ).strip().lower()

    # ======================================================
    # STATUS
    # ======================================================

    if tipo_evento == "status":

        return procesar_estado_mensaje(
            evento=evento,
            canal=canal,
        )

    # ======================================================
    # MENSAJE
    # ======================================================

    if tipo_evento == "message":

        return procesar_mensaje_entrante(
            evento=evento,
            canal=canal,
        )

    logger.debug(
        "Evento WhatsApp ignorado. tipo=%s",
        tipo_evento,
    )

    return None


# ==========================================================
# ESTADO DE MENSAJE
# ==========================================================


def procesar_estado_mensaje(
    evento,
    canal,
):
    """
    Procesa los estados enviados por Meta.

    Flujo normal:

        PENDIENTE
            ↓
        ENVIADO
            ↓
        ENTREGADO
            ↓
        LEIDO

    También:

        FALLIDO
    """

    external_id = str(
        evento.get(
            "external_id"
        )
        or ""
    ).strip()

    nuevo_estado = evento.get(
        "estado"
    )

    if (
        not external_id
        or not nuevo_estado
    ):
        return None

    mensaje = (
        Mensaje.objects
        .filter(
            external_id=external_id,
            conversacion__numero_canal=canal,
        )
        .first()
    )

    if mensaje is None:

        logger.debug(
            (
                "Estado recibido para mensaje "
                "no registrado. external_id=%s"
            ),
            external_id,
        )

        return None

    # ======================================================
    # FALLIDO TERMINAL
    # ======================================================

    if (
        mensaje.estado
        == Mensaje.EstadoMensaje.FALLIDO
    ):
        return mensaje

    # ======================================================
    # ACTUALIZAR ESTADO
    # ======================================================

    mensaje = actualizar_estado_mensaje(
        mensaje=mensaje,
        nuevo_estado=nuevo_estado,
        error_codigo=evento.get(
            "error_codigo"
        ),
        error_detalle=evento.get(
            "error_detalle"
        ),
    )

    # ======================================================
    # METADATA DEL STATUS
    # ======================================================

    metadata_evento = evento.get(
        "metadata"
    )

    if isinstance(
        metadata_evento,
        dict,
    ):

        metadata = dict(
            mensaje.metadata
            or {}
        )

        metadata[
            "ultimo_status_meta"
        ] = metadata_evento

        timestamp = evento.get(
            "timestamp"
        )

        if timestamp:

            try:

                metadata[
                    "ultimo_status_at"
                ] = timestamp.isoformat()

            except AttributeError:

                metadata[
                    "ultimo_status_at"
                ] = str(
                    timestamp
                )

        mensaje.metadata = metadata

        mensaje.save(
            update_fields=[
                "metadata",
                "updated_at",
            ]
        )

    return mensaje


# ==========================================================
# MENSAJE ENTRANTE
# ==========================================================


def procesar_mensaje_entrante(
    evento,
    canal,
):
    """
    Registra un mensaje recibido desde WhatsApp.

    Para un canal corporativo:

        Conversacion.sucursal = None

    es perfectamente válido.

    La sucursal podrá asignarse posteriormente mediante
    una referencia sincronizada desde MAO ERP.
    """

    wa_id = str(
        evento.get(
            "wa_id"
        )
        or ""
    ).strip()

    if not wa_id:

        logger.warning(
            "Mensaje WhatsApp recibido sin wa_id."
        )

        return None

    # ======================================================
    # 1. CONTACTO
    # ======================================================

    contacto, _ = (
        obtener_o_crear_contacto_whatsapp(
            wa_id=wa_id,
            nombre_perfil=evento.get(
                "nombre_perfil"
            ),
        )
    )

    # ======================================================
    # 2. CONVERSACIÓN
    # ======================================================

    conversacion = crear_conversacion(
        numero_canal=canal,

        # Para el WhatsApp corporativo puede ser None.
        sucursal=canal.sucursal,

        tipo=(
            Conversacion
            .TipoConversacion
            .INDIVIDUAL
        ),

        contacto=contacto,
    )

    # ======================================================
    # 3. MENSAJE AL QUE RESPONDE
    # ======================================================

    respuesta_a = None

    respuesta_a_external_id = str(
        evento.get(
            "respuesta_a_external_id"
        )
        or ""
    ).strip()

    if respuesta_a_external_id:

        respuesta_a = (
            Mensaje.objects
            .filter(
                conversacion=conversacion,
                external_id=(
                    respuesta_a_external_id
                ),
            )
            .first()
        )

    # ======================================================
    # 4. METADATA
    # ======================================================

    metadata = {}

    metadata_evento = evento.get(
        "metadata"
    )

    if isinstance(
        metadata_evento,
        dict,
    ):

        metadata.update(
            metadata_evento
        )

    metadata.update(
        {
            "proveedor":
                PROVEEDOR_IDENTIDAD_META,

            "phone_number_id":
                canal.identificador_externo,
        }
    )

    display_phone_number = evento.get(
        "display_phone_number"
    )

    if display_phone_number:

        metadata[
            "display_phone_number"
        ] = display_phone_number

    # ======================================================
    # 5. REGISTRAR MENSAJE
    # ======================================================

    mensaje, fue_creado = (
        registrar_mensaje_idempotente(
            conversacion=conversacion,
            external_id=evento.get(
                "external_id"
            ),
            direccion=(
                Mensaje
                .DireccionMensaje
                .ENTRANTE
            ),
            tipo=(
                evento.get(
                    "tipo"
                )
                or Mensaje.TipoMensaje.UNKNOWN
            ),
            texto_original=evento.get(
                "texto_original"
            ),
            fecha_mensaje=evento.get(
                "timestamp"
            ),
            remitente=contacto,
            estado=(
                Mensaje
                .EstadoMensaje
                .RECIBIDO
            ),
            respuesta_a=respuesta_a,
            metadata=metadata,
        )
    )

    # ======================================================
    # 6. WEBHOOK REPETIDO
    # ======================================================

    if not fue_creado:

        return mensaje

    # ======================================================
    # 7. MULTIMEDIA
    # ======================================================

    media_id = str(
        evento.get(
            "media_id"
        )
        or ""
    ).strip()

    if media_id:

        procesar_multimedia_entrante(
            mensaje=mensaje,
            media_id=media_id,
            nombre_original=evento.get(
                "nombre_archivo"
            ),
            mime_type_evento=evento.get(
                "mime_type"
            ),
        )

    return mensaje


# ==========================================================
# MULTIMEDIA ENTRANTE
# ==========================================================


def procesar_multimedia_entrante(
    mensaje,
    media_id,
    nombre_original=None,
    mime_type_evento=None,
):
    """
    Descarga y registra multimedia recibida desde Meta.

    Si no puede descargarse inmediatamente, conserva
    media_id para permitir un reintento futuro.
    """

    if mensaje is None:

        raise ValidationError(
            "Debe especificarse un mensaje."
        )

    media_id = str(
        media_id or ""
    ).strip()

    if not media_id:

        raise ValidationError(
            "Debe especificarse media_id."
        )

    nombre_original = str(
        nombre_original or ""
    ).strip()

    mime_type_evento = str(
        mime_type_evento or ""
    ).strip()

    # ======================================================
    # URL TEMPORAL
    # ======================================================

    media_url = obtener_url_descarga_media(
        media_id
    )

    content_bytes = None
    mime_type_descarga = None

    if media_url:

        (
            content_bytes,
            mime_type_descarga,
        ) = descargar_archivo_fisico(
            media_url
        )

    # ======================================================
    # DESCARGA CORRECTA
    # ======================================================

    if content_bytes:

        mime_type = (
            mime_type_descarga
            or mime_type_evento
            or "application/octet-stream"
        )

        # --------------------------------------------------
        # NOMBRE
        # --------------------------------------------------

        if not nombre_original:

            extension = (
                mimetypes.guess_extension(
                    mime_type
                )
                or ".bin"
            )

            if extension == ".jpe":

                extension = ".jpg"

            nombre_original = (
                f"{media_id}{extension}"
            )

        archivo = ContentFile(
            content_bytes,
            name=nombre_original,
        )

        return registrar_archivo_multimedia(
            mensaje=mensaje,
            identificador_externo=media_id,
            archivo=archivo,
            nombre_original=nombre_original,
            mime_type=mime_type,
            size_bytes=len(
                content_bytes
            ),
        )

    # ======================================================
    # DESCARGA PENDIENTE
    # ======================================================

    logger.warning(
        (
            "No fue posible descargar multimedia "
            "desde Meta. media_id=%s"
        ),
        media_id,
    )

    return registrar_archivo_multimedia(
        mensaje=mensaje,
        identificador_externo=media_id,
        archivo=None,
        nombre_original=(
            nombre_original
            or None
        ),
        mime_type=(
            mime_type_evento
            or None
        ),
        size_bytes=None,
    )


# ==========================================================
# VALIDAR CONVERSACIÓN DE SALIDA
# ==========================================================


def _validar_conversacion_whatsapp(
    conversacion,
):
    """
    Comprueba que una conversación pueda enviar
    contenido mediante WhatsApp.
    """

    if conversacion is None:

        raise ValidationError(
            "No se recibió una conversación válida."
        )

    if not isinstance(
        conversacion,
        Conversacion,
    ):

        raise ValidationError(
            "La conversación recibida no es válida."
        )

    if not conversacion.pk:

        raise ValidationError(
            "La conversación debe estar guardada."
        )

    # ======================================================
    # CANAL
    # ======================================================

    canal = conversacion.numero_canal

    if not canal.activo:

        raise WhatsAppConfiguracionError(
            "El canal está inactivo."
        )

    if (
        canal.proveedor
        != NumeroCanal.Proveedor.WHATSAPP
    ):

        raise WhatsAppConfiguracionError(
            (
                "El canal de la conversación "
                "no corresponde a WhatsApp."
            )
        )

    # ======================================================
    # CONTACTO
    # ======================================================

    contacto = conversacion.contacto

    if contacto is None:

        raise WhatsAppConfiguracionError(
            (
                "La conversación no tiene "
                "un contacto asociado."
            )
        )

    return (
        canal,
        contacto,
    )


# ==========================================================
# PHONE NUMBER ID
# ==========================================================


def _resolver_phone_number_id(
    canal,
):
    """
    Obtiene el phone_number_id del canal emisor.
    """

    phone_number_id = str(
        canal.identificador_externo
        or ""
    ).strip()

    if not phone_number_id:

        raise WhatsAppConfiguracionError(
            (
                "El canal de WhatsApp no tiene "
                "Phone Number ID configurado."
            )
        )

    return phone_number_id


# ==========================================================
# WA ID
# ==========================================================


def _resolver_wa_id(
    contacto,
):
    """
    Obtiene la identidad WhatsApp/Meta del contacto.
    """

    identidad = (
        IdentidadContactoExterna.objects
        .filter(
            contacto=contacto,
            proveedor=(
                PROVEEDOR_IDENTIDAD_META
            ),
        )
        .only(
            "identificador_externo",
        )
        .first()
    )

    if identidad is None:

        raise WhatsAppConfiguracionError(
            (
                "El contacto no tiene una identidad "
                "de WhatsApp registrada."
            )
        )

    wa_id = str(
        identidad.identificador_externo
        or ""
    ).strip()

    if not wa_id:

        raise WhatsAppConfiguracionError(
            (
                "La identidad WhatsApp del contacto "
                "no contiene un identificador válido."
            )
        )

    return wa_id


# ==========================================================
# TEXTO
# ==========================================================


def _normalizar_texto(
    texto,
):
    """
    Normaliza un mensaje de texto saliente.
    """

    texto = str(
        texto or ""
    ).strip()

    if not texto:

        raise ValidationError(
            "No se puede enviar un mensaje vacío."
        )

    return texto


# ==========================================================
# ERROR META
# ==========================================================


def _extraer_error_meta(
    response_meta,
):
    """
    Extrae error técnico de la respuesta normalizada
    del cliente Meta.
    """

    if not isinstance(
        response_meta,
        dict,
    ):

        return (
            "META_INVALID_RESPONSE",
            "Meta devolvió una respuesta inválida.",
        )

    error = response_meta.get(
        "error"
    )

    if not isinstance(
        error,
        dict,
    ):

        return (
            None,
            str(
                error
                or "Error desconocido de Meta."
            ),
        )

    codigo = (
        error.get(
            "code"
        )
        or error.get(
            "status_code"
        )
    )

    detalle = (
        error.get(
            "message"
        )
        or error.get(
            "type"
        )
        or "Error desconocido de Meta."
    )

    return (
        (
            str(codigo)
            if codigo is not None
            else None
        ),
        str(detalle),
    )


# ==========================================================
# GUARDAR WAMID
# ==========================================================


def _guardar_resultado_envio(
    mensaje,
    wamid,
    metadata_adicional=None,
):
    """
    Asocia el wamid devuelto por Meta con el mensaje
    local y marca el mensaje como ENVIADO.
    """

    wamid = str(
        wamid or ""
    ).strip()

    if not wamid:

        actualizar_estado_mensaje(
            mensaje=mensaje,
            nuevo_estado=(
                Mensaje
                .EstadoMensaje
                .FALLIDO
            ),
            error_codigo=(
                "META_WAMID_MISSING"
            ),
            error_detalle=(
                "Meta aceptó la solicitud pero "
                "no devolvió wamid."
            ),
        )

        raise WhatsAppEnvioError(
            "Meta no devolvió wamid."
        )

    metadata = dict(
        mensaje.metadata
        or {}
    )

    metadata[
        "wamid"
    ] = wamid

    if isinstance(
        metadata_adicional,
        dict,
    ):

        metadata.update(
            metadata_adicional
        )

    mensaje.external_id = wamid
    mensaje.metadata = metadata

    mensaje.save(
        update_fields=[
            "external_id",
            "metadata",
            "updated_at",
        ]
    )

    actualizar_estado_mensaje(
        mensaje=mensaje,
        nuevo_estado=(
            Mensaje
            .EstadoMensaje
            .ENVIADO
        ),
    )

    return mensaje


# ==========================================================
# ENVIAR TEXTO
# ==========================================================


def enviar_mensaje_saliente(
    conversacion,
    texto,
):
    """
    Envía un mensaje de texto mediante WhatsApp.

    Flujo:

        sistema consumidor
              ↓
        MAO Comunicaciones
              ↓
        Mensaje PENDIENTE
              ↓
        Meta
              ↓
        wamid
              ↓
        Mensaje ENVIADO

    ERP, MAO Citas y MAO Asistente nunca llaman
    directamente a Meta.
    """

    (
        canal,
        contacto,
    ) = _validar_conversacion_whatsapp(
        conversacion
    )

    phone_number_id = (
        _resolver_phone_number_id(
            canal
        )
    )

    wa_id = _resolver_wa_id(
        contacto
    )

    texto = _normalizar_texto(
        texto
    )

    # ======================================================
    # REGISTRAR INTENTO
    # ======================================================

    mensaje, _ = (
        registrar_mensaje_idempotente(
            conversacion=conversacion,
            external_id=None,
            direccion=(
                Mensaje
                .DireccionMensaje
                .SALIENTE
            ),
            tipo=(
                Mensaje
                .TipoMensaje
                .TEXT
            ),
            texto_original=texto,
            fecha_mensaje=timezone.now(),
            remitente=None,
            estado=(
                Mensaje
                .EstadoMensaje
                .PENDIENTE
            ),
            metadata={
                "proveedor":
                    PROVEEDOR_IDENTIDAD_META,

                "canal_id":
                    canal.pk,

                "phone_number_id":
                    phone_number_id,
            },
        )
    )

    # ======================================================
    # META
    # ======================================================

    try:

        response_meta = (
            enviar_mensaje_texto_meta(
                phone_number_id=(
                    phone_number_id
                ),
                wa_id=wa_id,
                text=texto,
            )
        )

    except Exception as exc:

        logger.exception(
            (
                "Error inesperado comunicándose "
                "con Meta. mensaje_local_id=%s"
            ),
            mensaje.pk,
        )

        actualizar_estado_mensaje(
            mensaje=mensaje,
            nuevo_estado=(
                Mensaje
                .EstadoMensaje
                .FALLIDO
            ),
            error_codigo=(
                "META_REQUEST_ERROR"
            ),
            error_detalle=(
                "No fue posible completar "
                "la solicitud hacia Meta."
            ),
        )

        raise WhatsAppEnvioError(
            (
                "No fue posible comunicarse "
                "con WhatsApp."
            )
        ) from exc

    # ======================================================
    # ERROR
    # ======================================================

    if (
        not isinstance(
            response_meta,
            dict,
        )
        or response_meta.get(
            "success"
        )
        is not True
    ):

        (
            error_codigo,
            error_detalle,
        ) = _extraer_error_meta(
            response_meta
        )

        actualizar_estado_mensaje(
            mensaje=mensaje,
            nuevo_estado=(
                Mensaje
                .EstadoMensaje
                .FALLIDO
            ),
            error_codigo=error_codigo,
            error_detalle=error_detalle,
        )

        raise WhatsAppEnvioError(
            "WhatsApp rechazó el envío."
        )

    # ======================================================
    # WAMID
    # ======================================================

    return _guardar_resultado_envio(
        mensaje=mensaje,
        wamid=response_meta.get(
            "wamid"
        ),
    )


# ==========================================================
# ENVIAR DOCUMENTO
# ==========================================================


def enviar_documento_saliente(
    conversacion,
    archivo_bytes,
    nombre_archivo,
    mime_type="application/pdf",
    caption=None,
):
    """
    Envía un documento mediante WhatsApp.

    Este método es genérico.

    Puede ser utilizado por:

        ERP
        MAO Citas
        MAO Asistente
        interfaz humana
        otros sistemas

    Ninguno necesita conocer la API de Meta.
    """

    (
        canal,
        contacto,
    ) = _validar_conversacion_whatsapp(
        conversacion
    )

    phone_number_id = (
        _resolver_phone_number_id(
            canal
        )
    )

    wa_id = _resolver_wa_id(
        contacto
    )

    # ======================================================
    # ARCHIVO
    # ======================================================

    if not isinstance(
        archivo_bytes,
        (
            bytes,
            bytearray,
        ),
    ):

        raise ValidationError(
            (
                "El contenido del documento "
                "debe ser binario."
            )
        )

    archivo_bytes = bytes(
        archivo_bytes
    )

    if not archivo_bytes:

        raise ValidationError(
            "El documento está vacío."
        )

    nombre_archivo = str(
        nombre_archivo or ""
    ).strip()

    if not nombre_archivo:

        raise ValidationError(
            (
                "Debe especificarse el "
                "nombre del documento."
            )
        )

    mime_type = str(
        mime_type or ""
    ).strip()

    if not mime_type:

        raise ValidationError(
            "Debe especificarse mime_type."
        )

    caption = str(
        caption or ""
    ).strip()

    # ======================================================
    # MENSAJE LOCAL PENDIENTE
    # ======================================================

    mensaje, _ = (
        registrar_mensaje_idempotente(
            conversacion=conversacion,
            external_id=None,
            direccion=(
                Mensaje
                .DireccionMensaje
                .SALIENTE
            ),
            tipo=(
                Mensaje
                .TipoMensaje
                .DOCUMENT
            ),
            texto_original=(
                caption
                or None
            ),
            fecha_mensaje=timezone.now(),
            remitente=None,
            estado=(
                Mensaje
                .EstadoMensaje
                .PENDIENTE
            ),
            metadata={
                "proveedor":
                    PROVEEDOR_IDENTIDAD_META,

                "canal_id":
                    canal.pk,

                "phone_number_id":
                    phone_number_id,
            },
        )
    )

    # ======================================================
    # GUARDAR ARCHIVO LOCAL
    # ======================================================

    archivo_local = ContentFile(
        archivo_bytes,
        name=nombre_archivo,
    )

    multimedia = (
        registrar_archivo_multimedia(
            mensaje=mensaje,
            archivo=archivo_local,
            identificador_externo=None,
            nombre_original=nombre_archivo,
            mime_type=mime_type,
            size_bytes=len(
                archivo_bytes
            ),
        )
    )

    # ======================================================
    # SUBIR A META
    # ======================================================

    try:

        resultado_subida = subir_media_meta(
            phone_number_id=(
                phone_number_id
            ),
            archivo_bytes=archivo_bytes,
            nombre_archivo=nombre_archivo,
            mime_type=mime_type,
        )

    except Exception as exc:

        logger.exception(
            "Error inesperado subiendo documento a Meta."
        )

        actualizar_estado_mensaje(
            mensaje=mensaje,
            nuevo_estado=(
                Mensaje
                .EstadoMensaje
                .FALLIDO
            ),
            error_codigo=(
                "META_MEDIA_UPLOAD_ERROR"
            ),
            error_detalle=(
                "No fue posible subir "
                "el documento a Meta."
            ),
        )

        raise WhatsAppEnvioError(
            (
                "No fue posible subir "
                "el documento a WhatsApp."
            )
        ) from exc

    # ======================================================
    # ERROR SUBIENDO
    # ======================================================

    if (
        not isinstance(
            resultado_subida,
            dict,
        )
        or resultado_subida.get(
            "success"
        )
        is not True
    ):

        (
            error_codigo,
            error_detalle,
        ) = _extraer_error_meta(
            resultado_subida
        )

        actualizar_estado_mensaje(
            mensaje=mensaje,
            nuevo_estado=(
                Mensaje
                .EstadoMensaje
                .FALLIDO
            ),
            error_codigo=error_codigo,
            error_detalle=error_detalle,
        )

        raise WhatsAppEnvioError(
            (
                "No fue posible subir "
                "el documento a WhatsApp."
            )
        )

    # ======================================================
    # MEDIA ID
    # ======================================================

    media_id = str(
        resultado_subida.get(
            "media_id"
        )
        or ""
    ).strip()

    if not media_id:

        actualizar_estado_mensaje(
            mensaje=mensaje,
            nuevo_estado=(
                Mensaje
                .EstadoMensaje
                .FALLIDO
            ),
            error_codigo=(
                "META_MEDIA_ID_MISSING"
            ),
            error_detalle=(
                "Meta no devolvió media_id."
            ),
        )

        raise WhatsAppEnvioError(
            "Meta no devolvió media_id."
        )

    # ======================================================
    # GUARDAR MEDIA ID
    # ======================================================

    multimedia.identificador_externo = (
        media_id
    )

    multimedia.save(
        update_fields=[
            "identificador_externo",
        ]
    )

    # ======================================================
    # ENVIAR DOCUMENTO
    # ======================================================

    try:

        resultado_envio = enviar_documento_meta(
            phone_number_id=(
                phone_number_id
            ),
            wa_id=wa_id,
            media_id=media_id,
            nombre_archivo=nombre_archivo,
            caption=(
                caption
                or None
            ),
        )

    except Exception as exc:

        logger.exception(
            "Error inesperado enviando documento."
        )

        actualizar_estado_mensaje(
            mensaje=mensaje,
            nuevo_estado=(
                Mensaje
                .EstadoMensaje
                .FALLIDO
            ),
            error_codigo=(
                "META_DOCUMENT_SEND_ERROR"
            ),
            error_detalle=(
                "El documento fue subido pero "
                "no pudo enviarse."
            ),
        )

        raise WhatsAppEnvioError(
            (
                "No fue posible enviar "
                "el documento."
            )
        ) from exc

    # ======================================================
    # ERROR ENVÍO
    # ======================================================

    if (
        not isinstance(
            resultado_envio,
            dict,
        )
        or resultado_envio.get(
            "success"
        )
        is not True
    ):

        (
            error_codigo,
            error_detalle,
        ) = _extraer_error_meta(
            resultado_envio
        )

        actualizar_estado_mensaje(
            mensaje=mensaje,
            nuevo_estado=(
                Mensaje
                .EstadoMensaje
                .FALLIDO
            ),
            error_codigo=error_codigo,
            error_detalle=error_detalle,
        )

        raise WhatsAppEnvioError(
            (
                "WhatsApp rechazó el "
                "envío del documento."
            )
        )

    # ======================================================
    # WAMID + ENVIADO
    # ======================================================

    return _guardar_resultado_envio(
        mensaje=mensaje,
        wamid=resultado_envio.get(
            "wamid"
        ),
        metadata_adicional={
            "media_id": media_id,
            "mime_type": mime_type,
            "nombre_archivo": (
                nombre_archivo
            ),
        },
    )