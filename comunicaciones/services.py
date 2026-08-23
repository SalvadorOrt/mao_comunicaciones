from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from comunicaciones.models import (
    ArchivoMultimedia,
    Contacto,
    Conversacion,
    IdentidadContactoExterna,
    Mensaje,
    NumeroCanal,
    Participante,
)


# =========================================================
# CONSTANTES
# =========================================================


PROVEEDOR_META = "META"


# =========================================================
# UTILIDADES
# =========================================================


def _normalizar_wa_id(wa_id):
    """
    Normaliza un identificador de WhatsApp recibido desde Meta.

    Ejemplo:

        593991234567

    No agrega lógica de cliente, ERP ni negocio.
    """

    wa_id = str(
        wa_id or ""
    ).strip()

    if not wa_id:
        raise ValidationError(
            "No se recibió un wa_id válido."
        )

    return wa_id


# =========================================================
# CONTACTO WHATSAPP
# =========================================================


def obtener_o_crear_contacto_whatsapp(
    wa_id,
    nombre_perfil=None,
):
    """
    Obtiene o crea un Contacto asociado a una identidad
    externa de WhatsApp/Meta.

    Meta identifica al usuario mediante wa_id.

    La identidad externa es la fuente técnica para evitar
    duplicados.

    Devuelve:

        (contacto, True)
            si se creó.

        (contacto, False)
            si ya existía.
    """

    wa_id = _normalizar_wa_id(
        wa_id
    )

    nombre_perfil = str(
        nombre_perfil or ""
    ).strip()

    # =====================================================
    # IDENTIDAD EXISTENTE
    # =====================================================

    identidad = (
        IdentidadContactoExterna.objects
        .select_related(
            "contacto",
        )
        .filter(
            proveedor=PROVEEDOR_META,
            identificador_externo=wa_id,
        )
        .first()
    )

    if identidad:

        contacto = identidad.contacto

        campos_actualizar = []

        # -------------------------------------------------
        # NOMBRE DE PERFIL
        # -------------------------------------------------

        if (
            nombre_perfil
            and contacto.nombre_perfil
            != nombre_perfil
        ):
            contacto.nombre_perfil = (
                nombre_perfil
            )

            campos_actualizar.append(
                "nombre_perfil"
            )

        # -------------------------------------------------
        # TELÉFONO
        # -------------------------------------------------

        telefono = f"+{wa_id}"

        if not contacto.numero_telefonico:
            contacto.numero_telefonico = (
                telefono
            )

            campos_actualizar.append(
                "numero_telefonico"
            )

        # -------------------------------------------------
        # GUARDAR
        # -------------------------------------------------

        if campos_actualizar:

            campos_actualizar.append(
                "updated_at"
            )

            contacto.save(
                update_fields=campos_actualizar
            )

        return (
            contacto,
            False,
        )

    # =====================================================
    # CREACIÓN CONCURRENTE SEGURA
    # =====================================================

    try:

        with transaction.atomic():

            contacto = Contacto.objects.create(
                nombre_perfil=(
                    nombre_perfil
                    or None
                ),
                numero_telefonico=(
                    f"+{wa_id}"
                ),
            )

            IdentidadContactoExterna.objects.create(
                contacto=contacto,
                proveedor=PROVEEDOR_META,
                identificador_externo=wa_id,
            )

            return (
                contacto,
                True,
            )

    except IntegrityError:

        # Otra solicitud pudo crear exactamente la
        # misma identidad al mismo tiempo.

        identidad = (
            IdentidadContactoExterna.objects
            .select_related(
                "contacto",
            )
            .get(
                proveedor=PROVEEDOR_META,
                identificador_externo=wa_id,
            )
        )

        return (
            identidad.contacto,
            False,
        )


# =========================================================
# CANAL PRINCIPAL
# =========================================================


def obtener_canal_principal(
    proveedor=NumeroCanal.Proveedor.WHATSAPP,
):
    """
    Obtiene el canal principal activo de un proveedor.

    Ejemplo:

        WhatsApp principal de MAO.

    No selecciona sucursales ni aplica lógica de negocio.
    """

    canal = (
        NumeroCanal.objects
        .filter(
            proveedor=proveedor,
            es_principal=True,
            activo=True,
        )
        .first()
    )

    if canal is None:
        raise ValidationError(
            (
                "No existe un canal principal activo "
                f"para el proveedor {proveedor}."
            )
        )

    return canal


# =========================================================
# CREAR / OBTENER CONVERSACIÓN
# =========================================================


def crear_conversacion(
    numero_canal,
    sucursal=None,
    tipo=Conversacion.TipoConversacion.INDIVIDUAL,
    contacto=None,
):
    """
    Obtiene o crea una conversación.

    La sucursal es OPCIONAL.

    Esto permite:

        Cliente
            ↓
        WhatsApp principal MAO
            ↓
        Conversacion.sucursal = NULL

    Posteriormente otro sistema puede indicar una sucursal
    válida proveniente del ERP.

    Para una conversación INDIVIDUAL se garantiza una sola
    conversación por:

        NumeroCanal + Contacto
    """

    if numero_canal is None:
        raise ValidationError(
            "Debe especificarse un canal."
        )

    if not numero_canal.pk:
        raise ValidationError(
            "El canal debe estar guardado."
        )

    if not numero_canal.activo:
        raise ValidationError(
            "El canal se encuentra inactivo."
        )

    # =====================================================
    # VALIDAR SUCURSAL SI EXISTE
    # =====================================================

    if sucursal is not None:

        if not sucursal.pk:
            raise ValidationError(
                "La sucursal debe estar guardada."
            )

        if not numero_canal.permite_sucursal(
            sucursal
        ):
            raise ValidationError(
                (
                    "La sucursal indicada no está "
                    "habilitada para este canal."
                )
            )

    # =====================================================
    # CONVERSACIÓN INDIVIDUAL EXISTENTE
    # =====================================================

    if (
        tipo
        == Conversacion.TipoConversacion.INDIVIDUAL
        and contacto is not None
    ):

        existente = (
            Conversacion.objects
            .filter(
                numero_canal=numero_canal,
                contacto=contacto,
                tipo=tipo,
            )
            .first()
        )

        if existente:
            return existente

    # =====================================================
    # CREAR
    # =====================================================

    try:

        with transaction.atomic():

            conversacion = Conversacion(
                numero_canal=numero_canal,
                sucursal=sucursal,
                tipo=tipo,
                contacto=contacto,
            )

            conversacion.full_clean()

            conversacion.save()

            return conversacion

    except IntegrityError:

        # Otra petición pudo crear simultáneamente la
        # misma conversación individual.

        if (
            tipo
            == Conversacion.TipoConversacion.INDIVIDUAL
            and contacto is not None
        ):

            return (
                Conversacion.objects
                .get(
                    numero_canal=numero_canal,
                    contacto=contacto,
                    tipo=tipo,
                )
            )

        raise


# =========================================================
# ASIGNAR SUCURSAL A CONVERSACIÓN
# =========================================================


def asignar_sucursal_conversacion(
    conversacion,
    sucursal,
):
    """
    Asocia una conversación con una referencia local
    de sucursal previamente sincronizada desde MAO ERP.

    Esta función NO crea sucursales.

    ERP sigue siendo la fuente de verdad.
    """

    if conversacion is None:
        raise ValidationError(
            "Debe especificarse una conversación."
        )

    if sucursal is None:

        conversacion.sucursal = None

        conversacion.save(
            update_fields=[
                "sucursal",
                "updated_at",
            ]
        )

        return conversacion

    if not sucursal.pk:
        raise ValidationError(
            "La sucursal debe estar guardada."
        )

    if not sucursal.activa:
        raise ValidationError(
            "La sucursal ERP está inactiva."
        )

    if not conversacion.numero_canal.permite_sucursal(
        sucursal
    ):
        raise ValidationError(
            (
                "La sucursal no está habilitada "
                "para el canal de esta conversación."
            )
        )

    conversacion.sucursal = sucursal

    conversacion.save(
        update_fields=[
            "sucursal",
            "updated_at",
        ]
    )

    return conversacion


# =========================================================
# REGISTRAR MENSAJE
# =========================================================


def registrar_mensaje_idempotente(
    conversacion,
    external_id=None,
    direccion=None,
    tipo=Mensaje.TipoMensaje.TEXT,
    texto_original=None,
    fecha_mensaje=None,
    remitente=None,
    estado=None,
    respuesta_a=None,
    metadata=None,
):
    """
    Registra un mensaje de forma idempotente.

    Meta puede enviar el mismo webhook varias veces.

    Por eso:

        Conversacion + external_id

    no puede generar mensajes duplicados.

    Para mensajes ENTRANTES, si no se especifica estado,
    se utiliza RECIBIDO.

    Para mensajes SALIENTES, si no se especifica estado,
    se utiliza PENDIENTE.

    Devuelve:

        (mensaje, True)
            mensaje nuevo.

        (mensaje, False)
            ya existía.
    """

    if conversacion is None:
        raise ValidationError(
            "Debe especificarse una conversación."
        )

    if direccion is None:
        raise ValidationError(
            "Debe especificarse la dirección del mensaje."
        )

    external_id = (
        str(external_id).strip()
        if external_id
        else None
    )

    if not fecha_mensaje:
        fecha_mensaje = timezone.now()

    if metadata is None:
        metadata = {}

    if not isinstance(
        metadata,
        dict,
    ):
        raise ValidationError(
            "metadata debe ser un diccionario."
        )

    # =====================================================
    # ESTADO PREDETERMINADO
    # =====================================================

    if estado is None:

        if (
            direccion
            == Mensaje.DireccionMensaje.ENTRANTE
        ):
            estado = (
                Mensaje.EstadoMensaje.RECIBIDO
            )

        else:
            estado = (
                Mensaje.EstadoMensaje.PENDIENTE
            )

    # =====================================================
    # IDEMPOTENCIA
    # =====================================================

    if external_id:

        existente = (
            Mensaje.objects
            .filter(
                conversacion=conversacion,
                external_id=external_id,
            )
            .first()
        )

        if existente:
            return (
                existente,
                False,
            )

    # =====================================================
    # INSERTAR
    # =====================================================

    try:

        with transaction.atomic():

            mensaje = Mensaje(
                conversacion=conversacion,
                external_id=external_id,
                remitente=remitente,
                direccion=direccion,
                tipo=tipo,
                texto_original=texto_original,
                estado=estado,
                fecha_mensaje=fecha_mensaje,
                respuesta_a=respuesta_a,
                metadata=metadata,
            )

            mensaje.full_clean()

            mensaje.save()

            # =================================================
            # ESTADO DE CONVERSACIÓN
            # =================================================

            update_fields = []

            if (
                conversacion.ultimo_mensaje_at is None
                or fecha_mensaje
                > conversacion.ultimo_mensaje_at
            ):

                conversacion.ultimo_mensaje_at = (
                    fecha_mensaje
                )

                update_fields.append(
                    "ultimo_mensaje_at"
                )

            # Un mensaje entrante requiere atención.
            if (
                direccion
                == Mensaje.DireccionMensaje.ENTRANTE
                and not conversacion.pendiente
            ):

                conversacion.pendiente = True

                update_fields.append(
                    "pendiente"
                )

            if update_fields:

                update_fields.append(
                    "updated_at"
                )

                conversacion.save(
                    update_fields=update_fields
                )

            return (
                mensaje,
                True,
            )

    except IntegrityError:

        if not external_id:
            raise

        existente = (
            Mensaje.objects
            .get(
                conversacion=conversacion,
                external_id=external_id,
            )
        )

        return (
            existente,
            False,
        )


# =========================================================
# ACTUALIZAR ESTADO DE MENSAJE
# =========================================================


def actualizar_estado_mensaje(
    mensaje,
    nuevo_estado,
    error_codigo=None,
    error_detalle=None,
):
    """
    Actualiza el estado técnico de transporte de un mensaje.

    Ejemplo WhatsApp:

        PENDIENTE
            ↓
        ENVIADO
            ↓
        ENTREGADO
            ↓
        LEIDO

    También puede quedar FALLIDO.

    No aplica ninguna lógica de citas, ERP o Asistente.
    """

    if mensaje is None:
        raise ValidationError(
            "Debe especificarse un mensaje."
        )

    estados_validos = {
        valor
        for valor, _ in (
            Mensaje.EstadoMensaje.choices
        )
    }

    if nuevo_estado not in estados_validos:
        raise ValidationError(
            "El estado del mensaje no es válido."
        )

    # =====================================================
    # EVITAR RETROCESOS
    # =====================================================

    progresion = {
        Mensaje.EstadoMensaje.PENDIENTE: 0,
        Mensaje.EstadoMensaje.ENVIADO: 1,
        Mensaje.EstadoMensaje.ENTREGADO: 2,
        Mensaje.EstadoMensaje.LEIDO: 3,
    }

    estado_actual = mensaje.estado

    if (
        estado_actual in progresion
        and nuevo_estado in progresion
        and progresion[nuevo_estado]
        < progresion[estado_actual]
    ):
        return mensaje

    # =====================================================
    # ACTUALIZAR
    # =====================================================

    mensaje.estado = nuevo_estado

    update_fields = [
        "estado",
        "updated_at",
    ]

    if nuevo_estado == Mensaje.EstadoMensaje.FALLIDO:

        mensaje.error_codigo = (
            str(error_codigo).strip()
            if error_codigo
            else None
        )

        mensaje.error_detalle = (
            str(error_detalle).strip()
            if error_detalle
            else None
        )

        update_fields.extend(
            [
                "error_codigo",
                "error_detalle",
            ]
        )

    else:

        # Si posteriormente Meta confirma correctamente
        # un mensaje, limpiamos errores anteriores.
        if mensaje.error_codigo:
            mensaje.error_codigo = None

            update_fields.append(
                "error_codigo"
            )

        if mensaje.error_detalle:
            mensaje.error_detalle = None

            update_fields.append(
                "error_detalle"
            )

    mensaje.save(
        update_fields=update_fields
    )

    return mensaje


# =========================================================
# REGISTRAR ARCHIVO MULTIMEDIA
# =========================================================


def registrar_archivo_multimedia(
    mensaje,
    identificador_externo=None,
    archivo=None,
    nombre_original=None,
    mime_type=None,
    size_bytes=None,
):
    """
    Registra metadata o contenido de un archivo asociado
    a un mensaje.

    Puede existir inicialmente solo con media_id.

    Ejemplo:

        Meta entrega media_id
              ↓
        se registra ArchivoMultimedia
              ↓
        posteriormente se descarga el archivo
    """

    if mensaje is None:
        raise ValidationError(
            "Debe especificarse un mensaje."
        )

    identificador_externo = (
        str(identificador_externo).strip()
        if identificador_externo
        else None
    )

    nombre_original = (
        str(nombre_original).strip()
        if nombre_original
        else None
    )

    mime_type = (
        str(mime_type).strip()
        if mime_type
        else None
    )

    if size_bytes is not None:

        try:
            size_bytes = int(
                size_bytes
            )

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise ValidationError(
                "size_bytes no es válido."
            ) from exc

        if size_bytes < 0:
            raise ValidationError(
                "size_bytes no puede ser negativo."
            )

    return ArchivoMultimedia.objects.create(
        mensaje=mensaje,
        archivo=archivo,
        identificador_externo=(
            identificador_externo
        ),
        nombre_original=nombre_original,
        mime_type=mime_type,
        size_bytes=size_bytes,
    )


# =========================================================
# PARTICIPANTES DE GRUPO
# =========================================================


def agregar_participante_grupo(
    grupo,
    contacto,
    es_administrador=False,
):
    """
    Registra un contacto como participante de un grupo.

    No crea duplicados.
    """

    if grupo is None:
        raise ValidationError(
            "Debe especificarse un grupo."
        )

    if contacto is None:
        raise ValidationError(
            "Debe especificarse un contacto."
        )

    participante, creado = (
        Participante.objects
        .get_or_create(
            grupo=grupo,
            contacto=contacto,
            defaults={
                "es_administrador":
                    bool(es_administrador),
            },
        )
    )

    return (
        participante,
        creado,
    )