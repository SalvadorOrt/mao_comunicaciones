import json
import logging
import mimetypes

from django.conf import settings
from django.core.files.base import ContentFile
from django.http import (
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from comunicaciones.models import (
    ArchivoMultimedia,
    Conversacion,
    Mensaje,
    NumeroCanal,
)
from comunicaciones.services import (
    crear_conversacion,
    obtener_o_crear_contacto_whatsapp,
    registrar_mensaje_idempotente,
)
from integraciones.whatsapp.client import (
    descargar_archivo_fisico,
    obtener_url_descarga_media,
)
from integraciones.whatsapp.parser import (
    parse_whatsapp_payload,
)
from integraciones.whatsapp.signature import (
    validate_hub_signature,
)


logger = logging.getLogger("django")


# ==========================================================
# WEBHOOK PRINCIPAL
# ==========================================================


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook_view(request):
    """
    Endpoint principal del webhook de WhatsApp Cloud API.

    GET:
        Verificación inicial realizada por Meta.

    POST:
        Recepción y procesamiento de eventos.
    """

    # ======================================================
    # GET - VERIFICACIÓN DE META
    # ======================================================

    if request.method == "GET":

        mode = request.GET.get(
            "hub.mode"
        )

        token = request.GET.get(
            "hub.verify_token"
        )

        challenge = request.GET.get(
            "hub.challenge"
        )

        meta_verify_token = getattr(
            settings,
            "META_VERIFY_TOKEN",
            None,
        )

        if not meta_verify_token:

            logger.error(
                "META_VERIFY_TOKEN no está configurado."
            )

            return HttpResponseForbidden(
                "Falta configuración de verificación."
            )

        if (
            mode == "subscribe"
            and token == meta_verify_token
        ):

            logger.info(
                "Verificación del webhook de Meta "
                "realizada correctamente."
            )

            return HttpResponse(
                challenge,
                status=200,
            )

        logger.warning(
            "Intento de verificación del webhook "
            "con token inválido."
        )

        return HttpResponseForbidden(
            "Token de verificación inválido."
        )

    # ======================================================
    # POST - EVENTOS DE META
    # ======================================================

    signature_header = request.headers.get(
        "X-Hub-Signature-256",
        "",
    )

    # ======================================================
    # VALIDAR FIRMA ANTES DE INTERPRETAR EL JSON
    # ======================================================

    if not validate_hub_signature(
        request.body,
        signature_header,
    ):

        return HttpResponseForbidden(
            "Firma de autenticidad inválida "
            "o ausente."
        )

    # ======================================================
    # DECODIFICAR JSON
    # ======================================================

    try:

        payload = json.loads(
            request.body.decode("utf-8")
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):

        logger.warning(
            "Meta envió un payload que no pudo "
            "decodificarse como JSON."
        )

        return JsonResponse(
            {
                "status": "error",
                "message": "Invalid JSON",
            },
            status=400,
        )

    # ======================================================
    # NORMALIZAR EVENTOS
    # ======================================================

    eventos = parse_whatsapp_payload(
        payload
    )

    # ======================================================
    # PROCESAR
    # ======================================================
    #
    # Si ocurre una falla interna inesperada,
    # devolvemos 500.
    #
    # Meta podrá reintentar el webhook y nuestra
    # idempotencia evita duplicar mensajes.
    # ======================================================

    try:

        for evento in eventos:
            _procesar_evento_webhook(
                evento
            )

    except Exception:

        logger.exception(
            "Error procesando un evento del "
            "webhook de WhatsApp."
        )

        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Webhook processing error"
                ),
            },
            status=500,
        )

    return HttpResponse(
        "EVENT_RECEIVED",
        status=200,
    )


# ==========================================================
# ROUTER DE EVENTOS
# ==========================================================


def _procesar_evento_webhook(
    evento: dict,
):
    """
    Procesa un evento normalizado.

    El phone_number_id recibido desde Meta identifica
    dinámicamente qué NumeroCanal recibió el evento.
    """

    phone_number_id = evento.get(
        "phone_number_id"
    )

    if not phone_number_id:

        logger.warning(
            "Evento de Meta sin phone_number_id."
        )

        return

    # ======================================================
    # RESOLVER CANAL
    # ======================================================

    canal = (
        NumeroCanal.objects
        .select_related(
            "sucursal",
        )
        .filter(
            identificador_externo=phone_number_id,
            activo=True,
        )
        .first()
    )

    if not canal:

        logger.warning(
            "Webhook recibido para un "
            "phone_number_id no registrado: %s",
            phone_number_id,
        )

        return

    tipo_evento = evento.get(
        "tipo_evento"
    )

    # ======================================================
    # ESTADO
    # ======================================================

    if tipo_evento == "status":

        _actualizar_estado_mensaje(
            evento,
            canal,
        )

        return

    # ======================================================
    # MENSAJE ENTRANTE
    # ======================================================

    if tipo_evento == "message":

        _procesar_mensaje_entrante(
            evento,
            canal,
        )

        return

    logger.debug(
        "Tipo de evento Meta ignorado: %s",
        tipo_evento,
    )


# ==========================================================
# ACTUALIZAR ESTADO
# ==========================================================


def _actualizar_estado_mensaje(
    evento: dict,
    canal: NumeroCanal,
):
    """
    Actualiza el estado de un mensaje saliente.

    Estados normales:

        ENVIADO
          ↓
        ENTREGADO
          ↓
        LEIDO

    FALLIDO se considera terminal.
    """

    external_id = evento.get(
        "external_id"
    )

    nuevo_estado = evento.get(
        "estado"
    )

    if not external_id or not nuevo_estado:
        return

    mensaje = (
        Mensaje.objects
        .filter(
            external_id=external_id,
            conversacion__numero_canal=canal,
        )
        .first()
    )

    if not mensaje:

        logger.debug(
            "Estado recibido para un mensaje "
            "no registrado. external_id=%s",
            external_id,
        )

        return

    # ======================================================
    # FALLIDO YA ES TERMINAL
    # ======================================================

    if (
        mensaje.estado
        == Mensaje.EstadoMensaje.FALLIDO
    ):
        return

    # ======================================================
    # META REPORTA FALLO
    # ======================================================

    if (
        nuevo_estado
        == Mensaje.EstadoMensaje.FALLIDO
    ):

        Mensaje.objects.filter(
            pk=mensaje.pk
        ).update(
            estado=Mensaje.EstadoMensaje.FALLIDO
        )

        logger.error(
            "Meta reportó fallo de entrega. "
            "external_id=%s",
            external_id,
        )

        return

    # ======================================================
    # PROGRESIÓN MONÓTONA
    # ======================================================

    orden_estados = {
        Mensaje.EstadoMensaje.RECIBIDO: 0,
        Mensaje.EstadoMensaje.ENVIADO: 1,
        Mensaje.EstadoMensaje.ENTREGADO: 2,
        Mensaje.EstadoMensaje.LEIDO: 3,
    }

    estado_actual_orden = (
        orden_estados.get(
            mensaje.estado,
            0,
        )
    )

    nuevo_estado_orden = (
        orden_estados.get(
            nuevo_estado
        )
    )

    if nuevo_estado_orden is None:
        return

    if (
        nuevo_estado_orden
        <= estado_actual_orden
    ):
        return

    Mensaje.objects.filter(
        pk=mensaje.pk
    ).update(
        estado=nuevo_estado
    )


# ==========================================================
# MENSAJE ENTRANTE
# ==========================================================


def _procesar_mensaje_entrante(
    evento: dict,
    canal: NumeroCanal,
):
    """
    Persiste un mensaje recibido desde WhatsApp.
    """

    wa_id = evento.get(
        "wa_id"
    )

    if not wa_id:

        logger.warning(
            "Mensaje recibido sin wa_id."
        )

        return

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

    conversacion = (
        Conversacion.objects
        .filter(
            numero_canal=canal,
            contacto=contacto,
            tipo=(
                Conversacion
                .TipoConversacion
                .INDIVIDUAL
            ),
        )
        .first()
    )

    if not conversacion:

        conversacion = crear_conversacion(
            numero_canal=canal,
            sucursal=canal.sucursal,
            tipo=(
                Conversacion
                .TipoConversacion
                .INDIVIDUAL
            ),
            privacidad=(
                Conversacion
                .PrivacidadConversacion
                .SIN_CLASIFICAR
            ),
            contacto=contacto,
        )

    # ======================================================
    # 3. MENSAJE AL QUE RESPONDE
    # ======================================================

    respuesta_a = None

    respuesta_a_external_id = evento.get(
        "respuesta_a_external_id"
    )

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
    # 4. PERSISTIR
    # ======================================================

    mensaje, fue_creado = (
        registrar_mensaje_idempotente(
            conversacion=conversacion,
            external_id=evento.get(
                "external_id"
            ),
            direccion=evento.get(
                "direccion"
            ),
            tipo=evento.get(
                "tipo"
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
        )
    )

    # ======================================================
    # 5. MULTIMEDIA
    # ======================================================

    media_id = evento.get(
        "media_id"
    )

    if fue_creado and media_id:

        _descargar_y_guardar_multimedia(
            mensaje,
            media_id,
        )


# ==========================================================
# MULTIMEDIA
# ==========================================================


def _descargar_y_guardar_multimedia(
    mensaje: Mensaje,
    media_id: str,
):
    """
    Descarga un adjunto desde Meta.

    Por ahora el proceso es síncrono.

    Más adelante puede moverse a una cola de trabajos
    sin modificar el contrato del webhook.
    """

    media_url = (
        obtener_url_descarga_media(
            media_id
        )
    )

    content_bytes = None
    mime_type = None

    if media_url:

        (
            content_bytes,
            mime_type,
        ) = descargar_archivo_fisico(
            media_url
        )

    # ======================================================
    # DESCARGA CORRECTA
    # ======================================================

    if content_bytes:

        extension = (
            mimetypes.guess_extension(
                mime_type or ""
            )
            or ".bin"
        )

        if extension == ".jpe":
            extension = ".jpg"

        file_name = (
            f"{media_id}{extension}"
        )

        ArchivoMultimedia.objects.create(
            mensaje=mensaje,
            identificador_externo=media_id,
            mime_type=(
                mime_type
                or "application/octet-stream"
            ),
            nombre_original=file_name,
            size_bytes=len(
                content_bytes
            ),
            archivo=ContentFile(
                content_bytes,
                name=file_name,
            ),
        )

        return

    # ======================================================
    # DESCARGA PENDIENTE
    # ======================================================

    logger.warning(
        "No fue posible descargar el archivo "
        "de Meta. media_id=%s",
        media_id,
    )

    ArchivoMultimedia.objects.create(
        mensaje=mensaje,
        identificador_externo=media_id,
        mime_type="application/octet-stream",
        nombre_original=(
            f"pending_{media_id}.bin"
        ),
    )