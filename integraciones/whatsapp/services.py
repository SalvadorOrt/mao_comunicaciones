from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from comunicaciones.models import (
    IdentidadContactoExterna,
    Mensaje,
)

from integraciones.whatsapp.client import (
    enviar_mensaje_texto_meta,
)


# ==========================================================
# ENVÍO SALIENTE
# ==========================================================


def enviar_mensaje_saliente(
    conversacion,
    texto,
):
    """
    Envía un mensaje de texto desde una conversación
    de MAO Comunicaciones mediante WhatsApp Cloud API.

    Este servicio NO decide si un usuario humano tiene
    autorización para realizar la operación.

    La autorización debe ocurrir en la capa que invoque
    este servicio:

        - API interna autenticada
        - interfaz administrativa
        - MAO ERP
        - MAO Asistente

    Responsabilidades de este servicio:

        1. Resolver el canal.
        2. Resolver Phone Number ID.
        3. Resolver destinatario Meta.
        4. Validar contenido.
        5. Enviar mediante Meta.
        6. Persistir el mensaje saliente.
    """

    # ======================================================
    # 1. CONVERSACIÓN
    # ======================================================

    if conversacion is None:
        raise ValidationError(
            "No se recibió una conversación válida."
        )

    canal = getattr(
        conversacion,
        "numero_canal",
        None,
    )

    contacto = getattr(
        conversacion,
        "contacto",
        None,
    )

    if not canal:
        raise ValidationError(
            "La conversación no tiene un canal "
            "de comunicación configurado."
        )

    if not contacto:
        raise ValidationError(
            "La conversación no tiene un contacto asociado."
        )

    # ======================================================
    # 2. PHONE NUMBER ID
    # ======================================================

    phone_number_id = (
        canal.identificador_externo
    )

    if not phone_number_id:
        raise ValidationError(
            "El canal no tiene configurado su "
            "Phone Number ID de Meta."
        )

    # ======================================================
    # 3. DESTINATARIO META
    # ======================================================

    identidad_meta = (
        IdentidadContactoExterna.objects
        .filter(
            contacto=contacto,
            proveedor="META",
        )
        .first()
    )

    if (
        identidad_meta
        and identidad_meta.identificador_externo
    ):
        wa_id = (
            identidad_meta.identificador_externo
        )

    # Compatibilidad temporal con contactos
    # creados antes de IdentidadContactoExterna.
    elif contacto.identificador_externo:

        wa_id = contacto.identificador_externo

    else:
        raise ValidationError(
            "El contacto no tiene una identidad "
            "de WhatsApp configurada."
        )

    # ======================================================
    # 4. TEXTO
    # ======================================================

    texto = (
        texto
        or ""
    ).strip()

    if not texto:
        raise ValidationError(
            "No se puede enviar un mensaje vacío."
        )

    # ======================================================
    # 5. META
    # ======================================================
    #
    # IMPORTANTE:
    # Esta llamada ocurre FUERA de una transacción SQL.
    # No mantenemos bloqueada la base de datos mientras
    # esperamos la respuesta HTTP de Meta.
    # ======================================================

    response_meta = enviar_mensaje_texto_meta(
        phone_number_id=phone_number_id,
        wa_id=wa_id,
        text=texto,
    )

    if response_meta.get("success") is not True:

        error_details = response_meta.get(
            "error",
            "Error desconocido",
        )

        raise ValidationError(
            "Error enviando mensaje mediante Meta: "
            f"{error_details}"
        )

    # ======================================================
    # 6. WAMID
    # ======================================================

    wamid = response_meta.get(
        "wamid"
    )

    if not wamid:
        raise ValidationError(
            "Meta aceptó la solicitud pero no devolvió "
            "el identificador wamid."
        )

    # ======================================================
    # 7. PERSISTENCIA
    # ======================================================

    with transaction.atomic():

        mensaje = Mensaje.objects.create(
            conversacion=conversacion,
            external_id=wamid,
            remitente=None,
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
            estado=(
                Mensaje
                .EstadoMensaje
                .ENVIADO
            ),
            fecha_mensaje=timezone.now(),
        )

    return mensaje