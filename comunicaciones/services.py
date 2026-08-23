from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from comunicaciones.models import (
    Contacto,
    Conversacion,
    IdentidadContactoExterna,
    Mensaje,
    Participante,
)


# =========================================================
# CONTACTO WHATSAPP
# =========================================================


def obtener_o_crear_contacto_whatsapp(
    wa_id,
    nombre_perfil=None,
):
    """
    Localiza o crea de forma segura un Contacto y su
    IdentidadContactoExterna de Meta.

    wa_id es el identificador de WhatsApp del contacto.

    Ejemplo:
        593991234567
    """

    wa_id = str(
        wa_id or ""
    ).strip()

    if not wa_id:
        raise ValidationError(
            "No se recibió un wa_id válido."
        )

    nombre_perfil = (
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
            proveedor="META",
            identificador_externo=wa_id,
        )
        .first()
    )

    if identidad:

        contacto = identidad.contacto

        # Si anteriormente Meta no había entregado nombre,
        # podemos completar el dato sin sobrescribir uno
        # ya existente.
        if (
            nombre_perfil
            and not contacto.nombre_perfil
        ):
            contacto.nombre_perfil = (
                nombre_perfil
            )

            contacto.save(
                update_fields=[
                    "nombre_perfil",
                ]
            )

        return (
            contacto,
            False,
        )

    # =====================================================
    # CREACIÓN SEGURA
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
                proveedor="META",
                identificador_externo=wa_id,
            )

            return (
                contacto,
                True,
            )

    except IntegrityError:

        # Otra petición pudo crear la identidad
        # exactamente al mismo tiempo.

        identidad = (
            IdentidadContactoExterna.objects
            .select_related(
                "contacto",
            )
            .get(
                proveedor="META",
                identificador_externo=wa_id,
            )
        )

        return (
            identidad.contacto,
            False,
        )


# =========================================================
# CREAR CONVERSACIÓN
# =========================================================


def crear_conversacion(
    numero_canal,
    sucursal,
    tipo=Conversacion.TipoConversacion.INDIVIDUAL,
    privacidad=(
        Conversacion
        .PrivacidadConversacion
        .SIN_CLASIFICAR
    ),
    contacto=None,
):
    """
    Crea una conversación.

    Para conversaciones individuales garantiza que
    no existan dos conversaciones para:

        NumeroCanal + Contacto
    """

    if numero_canal is None:
        raise ValidationError(
            "Debe especificarse un canal."
        )

    if sucursal is None:
        raise ValidationError(
            "Debe especificarse una sucursal."
        )

    # =====================================================
    # INDIVIDUAL EXISTENTE
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
                privacidad=privacidad,
                contacto=contacto,
            )

            conversacion.full_clean()
            conversacion.save()

            return conversacion

    except IntegrityError:

        # En caso de carrera concurrente para una
        # conversación individual, recuperamos la
        # conversación que ganó la inserción.

        if (
            tipo
            == Conversacion.TipoConversacion.INDIVIDUAL
            and contacto is not None
        ):
            return Conversacion.objects.get(
                numero_canal=numero_canal,
                contacto=contacto,
                tipo=tipo,
            )

        raise


# =========================================================
# REGISTRAR MENSAJE
# =========================================================


def registrar_mensaje_idempotente(
    conversacion,
    external_id,
    direccion,
    tipo,
    texto_original,
    fecha_mensaje=None,
    remitente=None,
    estado=Mensaje.EstadoMensaje.RECIBIDO,
    respuesta_a=None,
):
    """
    Persiste un mensaje de forma idempotente.

    Meta puede reenviar un mismo webhook más de una vez.

    Por eso:

        Conversacion + external_id

    no debe generar mensajes duplicados.

    Devuelve:

        (mensaje, True)
            si fue creado.

        (mensaje, False)
            si ya existía.
    """

    if conversacion is None:
        raise ValidationError(
            "Debe especificarse una conversación."
        )

    if not fecha_mensaje:
        fecha_mensaje = timezone.now()

    # =====================================================
    # RUTA RÁPIDA
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
            )

            mensaje.full_clean()
            mensaje.save()

            # =================================================
            # ESTADO DE LA CONVERSACIÓN
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

            # Un mensaje entrante nuevo queda pendiente
            # de atención.
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
# PARTICIPANTES DE GRUPO
# =========================================================


def agregar_participante_grupo(
    grupo,
    contacto,
    es_administrador=False,
):
    """
    Agrega un contacto a un grupo.

    Si ya existe como participante no crea
    un duplicado.
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
                    es_administrador,
            },
        )
    )

    return (
        participante,
        creado,
    )