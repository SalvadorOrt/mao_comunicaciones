import logging
from datetime import datetime, timezone as datetime_timezone

from django.utils import timezone

from comunicaciones.models import Mensaje


logger = logging.getLogger("django")


# ==========================================================
# PARSER PRINCIPAL
# ==========================================================


def parse_whatsapp_payload(payload: dict) -> list:
    """
    Parsea de forma segura un payload de WhatsApp Cloud API.

    Convierte la estructura externa de Meta en eventos
    normalizados utilizados internamente por
    MAO Comunicaciones.

    El JSON recibido se trata exclusivamente como datos.
    """

    eventos = []

    try:
        if payload.get("object") != "whatsapp_business_account":
            logger.warning(
                "Payload ignorado porque no corresponde a "
                "'whatsapp_business_account'."
            )
            return eventos

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):

                value = change.get("value", {})

                # ==========================================
                # CANAL RECEPTOR
                # ==========================================

                phone_number_id = (
                    value.get("metadata", {})
                    .get("phone_number_id")
                )

                if not phone_number_id:
                    continue

                # ==========================================
                # MENSAJES ENTRANTES
                # ==========================================

                for message in value.get("messages", []):

                    wa_id = message.get("from")

                    evento = {
                        "tipo_evento":
                            "message",

                        "phone_number_id":
                            phone_number_id,

                        "wa_id":
                            wa_id,

                        "external_id":
                            message.get("id"),

                        "timestamp":
                            _parse_timestamp(
                                message.get("timestamp")
                            ),

                        "nombre_perfil":
                            _extract_profile_name(
                                value.get("contacts", []),
                                wa_id,
                            ),

                        "direccion":
                            Mensaje.DireccionMensaje.ENTRANTE,

                        "tipo":
                            _map_message_type(
                                message.get("type")
                            ),

                        "texto_original":
                            _extract_text(message),

                        "respuesta_a_external_id":
                            _extract_reply_to(message),

                        "media_id":
                            _extract_media_id(message),
                    }

                    eventos.append(evento)

                # ==========================================
                # ESTADOS DE MENSAJES
                # ==========================================

                for status in value.get("statuses", []):

                    evento = {
                        "tipo_evento":
                            "status",

                        "phone_number_id":
                            phone_number_id,

                        "wa_id":
                            status.get("recipient_id"),

                        "external_id":
                            status.get("id"),

                        "timestamp":
                            _parse_timestamp(
                                status.get("timestamp")
                            ),

                        "estado":
                            _map_status_type(
                                status.get("status")
                            ),
                    }

                    eventos.append(evento)

    except Exception:
        logger.exception(
            "Error inesperado parseando payload "
            "de WhatsApp."
        )

    return eventos


# ==========================================================
# TIMESTAMP
# ==========================================================


def _parse_timestamp(ts_string: str):
    """
    Convierte un timestamp UNIX enviado por Meta
    a datetime timezone-aware.
    """

    if not ts_string:
        return timezone.now()

    try:
        return datetime.fromtimestamp(
            int(ts_string),
            tz=datetime_timezone.utc,
        )

    except (ValueError, TypeError):
        return timezone.now()


# ==========================================================
# PERFIL
# ==========================================================


def _extract_profile_name(
    contacts_array: list,
    wa_id: str,
) -> str:
    """
    Obtiene el nombre de perfil asociado al wa_id.
    """

    for contact in contacts_array:

        if contact.get("wa_id") == wa_id:
            return (
                contact.get("profile", {})
                .get("name", "")
            )

    return ""


# ==========================================================
# TIPO DE MENSAJE
# ==========================================================


def _map_message_type(meta_type: str) -> str:
    """
    Mapea tipos de Meta al dominio interno.
    """

    tipos_soportados = {
        "text":
            Mensaje.TipoMensaje.TEXT,

        # Estos dos contienen interacción textual.
        "button":
            Mensaje.TipoMensaje.TEXT,

        "interactive":
            Mensaje.TipoMensaje.TEXT,

        "audio":
            Mensaje.TipoMensaje.AUDIO,

        "image":
            Mensaje.TipoMensaje.IMAGE,

        "video":
            Mensaje.TipoMensaje.VIDEO,

        "document":
            Mensaje.TipoMensaje.DOCUMENT,

        "location":
            Mensaje.TipoMensaje.LOCATION,

        "contacts":
            Mensaje.TipoMensaje.CONTACT,

        "reaction":
            Mensaje.TipoMensaje.REACTION,

        "sticker":
            Mensaje.TipoMensaje.STICKER,
    }

    return tipos_soportados.get(
        meta_type,
        Mensaje.TipoMensaje.UNKNOWN,
    )


# ==========================================================
# ESTADO
# ==========================================================


def _map_status_type(meta_status: str):
    """
    Mapea estados de entrega de Meta.
    """

    estados_soportados = {
        "sent":
            Mensaje.EstadoMensaje.ENVIADO,

        "delivered":
            Mensaje.EstadoMensaje.ENTREGADO,

        "read":
            Mensaje.EstadoMensaje.LEIDO,

        "failed":
            Mensaje.EstadoMensaje.FALLIDO,
    }

    return estados_soportados.get(
        meta_status
    )


# ==========================================================
# TEXTO
# ==========================================================


def _extract_text(message: dict) -> str:
    """
    Extrae contenido textual según el tipo de mensaje.
    """

    m_type = message.get("type")

    if m_type == "text":
        return (
            message.get("text", {})
            .get("body", "")
        )

    if m_type == "button":
        return (
            message.get("button", {})
            .get("text", "")
        )

    if m_type == "interactive":

        interactive = message.get(
            "interactive",
            {},
        )

        # Respuesta a botón
        button_reply = (
            interactive
            .get("button_reply", {})
            .get("title")
        )

        if button_reply:
            return button_reply

        # Respuesta a lista
        list_reply = (
            interactive
            .get("list_reply", {})
            .get("title")
        )

        return list_reply or ""

    if m_type in [
        "image",
        "video",
        "document",
    ]:
        return (
            message.get(m_type, {})
            .get("caption", "")
        )

    if m_type == "unknown":
        return (
            "Formato de mensaje de Meta "
            "no soportado."
        )

    return ""


# ==========================================================
# RESPUESTAS
# ==========================================================


def _extract_reply_to(message: dict):
    """
    Obtiene el external_id del mensaje original
    cuando el mensaje actual es una respuesta.
    """

    context = message.get(
        "context",
        {},
    )

    return context.get("id")


# ==========================================================
# MULTIMEDIA
# ==========================================================


def _extract_media_id(message: dict):
    """
    Obtiene el media_id de Meta cuando el evento
    contiene un archivo multimedia.
    """

    m_type = message.get("type")

    if m_type in [
        "audio",
        "image",
        "video",
        "document",
        "sticker",
    ]:
        return (
            message.get(m_type, {})
            .get("id")
        )

    return None