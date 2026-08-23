# integraciones/whatsapp/parser.py

import logging
from datetime import (
    datetime,
    timezone as datetime_timezone,
)

from django.utils import timezone

from comunicaciones.models import Mensaje


logger = logging.getLogger(__name__)


# ==========================================================
# PARSER PRINCIPAL
# ==========================================================


def parse_whatsapp_payload(
    payload: dict,
) -> list:
    """
    Convierte el payload externo de WhatsApp Cloud API
    en eventos normalizados utilizados internamente por
    MAO Comunicaciones.

    Este parser:

        - NO guarda nada en base de datos;
        - NO llama al ERP;
        - NO agenda citas;
        - NO utiliza IA;
        - NO aplica lógica de negocio.

    Únicamente transforma datos de Meta a un contrato
    interno estable.
    """

    eventos = []

    # ======================================================
    # VALIDACIÓN BÁSICA
    # ======================================================

    if not isinstance(
        payload,
        dict,
    ):
        return eventos

    if (
        payload.get("object")
        != "whatsapp_business_account"
    ):

        logger.debug(
            (
                "Payload ignorado porque no corresponde "
                "a whatsapp_business_account."
            )
        )

        return eventos

    # ======================================================
    # ENTRIES
    # ======================================================

    entries = payload.get(
        "entry",
        [],
    )

    if not isinstance(
        entries,
        list,
    ):
        return eventos

    for entry in entries:

        if not isinstance(
            entry,
            dict,
        ):
            continue

        changes = entry.get(
            "changes",
            [],
        )

        if not isinstance(
            changes,
            list,
        ):
            continue

        for change in changes:

            if not isinstance(
                change,
                dict,
            ):
                continue

            value = change.get(
                "value",
                {},
            )

            if not isinstance(
                value,
                dict,
            ):
                continue

            # =================================================
            # METADATA DEL NÚMERO RECEPTOR
            # =================================================

            metadata_meta = value.get(
                "metadata",
                {},
            )

            if not isinstance(
                metadata_meta,
                dict,
            ):
                metadata_meta = {}

            phone_number_id = str(
                metadata_meta.get(
                    "phone_number_id"
                )
                or ""
            ).strip()

            display_phone_number = str(
                metadata_meta.get(
                    "display_phone_number"
                )
                or ""
            ).strip()

            # Sin phone_number_id no podemos saber
            # qué NumeroCanal recibió el evento.
            if not phone_number_id:
                continue

            # =================================================
            # MENSAJES ENTRANTES
            # =================================================

            messages = value.get(
                "messages",
                [],
            )

            if isinstance(
                messages,
                list,
            ):

                for message in messages:

                    if not isinstance(
                        message,
                        dict,
                    ):
                        continue

                    evento = (
                        _parse_message_event(
                            message=message,
                            value=value,
                            phone_number_id=(
                                phone_number_id
                            ),
                            display_phone_number=(
                                display_phone_number
                            ),
                        )
                    )

                    if evento:
                        eventos.append(
                            evento
                        )

            # =================================================
            # ESTADOS DE MENSAJES SALIENTES
            # =================================================

            statuses = value.get(
                "statuses",
                [],
            )

            if isinstance(
                statuses,
                list,
            ):

                for status in statuses:

                    if not isinstance(
                        status,
                        dict,
                    ):
                        continue

                    evento = (
                        _parse_status_event(
                            status=status,
                            phone_number_id=(
                                phone_number_id
                            ),
                            display_phone_number=(
                                display_phone_number
                            ),
                        )
                    )

                    if evento:
                        eventos.append(
                            evento
                        )

    return eventos


# ==========================================================
# MENSAJE ENTRANTE
# ==========================================================


def _parse_message_event(
    *,
    message: dict,
    value: dict,
    phone_number_id: str,
    display_phone_number: str,
):
    """
    Normaliza un mensaje entrante.
    """

    wa_id = str(
        message.get(
            "from"
        )
        or ""
    ).strip()

    external_id = str(
        message.get(
            "id"
        )
        or ""
    ).strip()

    meta_type = str(
        message.get(
            "type"
        )
        or ""
    ).strip().lower()

    if not wa_id:
        return None

    # ======================================================
    # CONTACTO
    # ======================================================

    contacts = value.get(
        "contacts",
        [],
    )

    if not isinstance(
        contacts,
        list,
    ):
        contacts = []

    nombre_perfil = (
        _extract_profile_name(
            contacts_array=contacts,
            wa_id=wa_id,
        )
    )

    # ======================================================
    # EVENTO NORMALIZADO
    # ======================================================

    return {
        "tipo_evento":
            "message",

        "phone_number_id":
            phone_number_id,

        "display_phone_number":
            display_phone_number,

        "wa_id":
            wa_id,

        "external_id":
            (
                external_id
                or None
            ),

        "timestamp":
            _parse_timestamp(
                message.get(
                    "timestamp"
                )
            ),

        "nombre_perfil":
            nombre_perfil,

        "direccion":
            (
                Mensaje
                .DireccionMensaje
                .ENTRANTE
            ),

        "tipo":
            _map_message_type(
                meta_type
            ),

        "texto_original":
            _extract_text(
                message
            ),

        "respuesta_a_external_id":
            _extract_reply_to(
                message
            ),

        "media_id":
            _extract_media_id(
                message
            ),

        "mime_type":
            _extract_mime_type(
                message
            ),

        "nombre_archivo":
            _extract_filename(
                message
            ),

        "metadata":
            _extract_message_metadata(
                message=message,
                meta_type=meta_type,
                display_phone_number=(
                    display_phone_number
                ),
            ),
    }


# ==========================================================
# STATUS
# ==========================================================


def _parse_status_event(
    *,
    status: dict,
    phone_number_id: str,
    display_phone_number: str,
):
    """
    Normaliza un estado de entrega recibido desde Meta.
    """

    external_id = str(
        status.get(
            "id"
        )
        or ""
    ).strip()

    meta_status = str(
        status.get(
            "status"
        )
        or ""
    ).strip().lower()

    estado = _map_status_type(
        meta_status
    )

    # Estado desconocido:
    # conservamos el comportamiento seguro y lo ignoramos.
    if estado is None:
        return None

    (
        error_codigo,
        error_detalle,
    ) = _extract_status_error(
        status
    )

    return {
        "tipo_evento":
            "status",

        "phone_number_id":
            phone_number_id,

        "display_phone_number":
            display_phone_number,

        "wa_id":
            (
                str(
                    status.get(
                        "recipient_id"
                    )
                    or ""
                ).strip()
                or None
            ),

        "external_id":
            (
                external_id
                or None
            ),

        "timestamp":
            _parse_timestamp(
                status.get(
                    "timestamp"
                )
            ),

        "estado":
            estado,

        "error_codigo":
            error_codigo,

        "error_detalle":
            error_detalle,

        "metadata":
            _extract_status_metadata(
                status=status,
                meta_status=meta_status,
                display_phone_number=(
                    display_phone_number
                ),
            ),
    }


# ==========================================================
# TIMESTAMP
# ==========================================================


def _parse_timestamp(
    ts_string,
):
    """
    Convierte el timestamp UNIX enviado por Meta en
    datetime timezone-aware.

    Si no puede interpretarse, utiliza la hora actual.
    """

    if ts_string in (
        None,
        "",
    ):
        return timezone.now()

    try:

        return datetime.fromtimestamp(
            int(ts_string),
            tz=datetime_timezone.utc,
        )

    except (
        ValueError,
        TypeError,
        OverflowError,
        OSError,
    ):

        logger.warning(
            "Timestamp inválido recibido desde Meta."
        )

        return timezone.now()


# ==========================================================
# PERFIL
# ==========================================================


def _extract_profile_name(
    contacts_array: list,
    wa_id: str,
) -> str:
    """
    Obtiene el nombre de perfil que Meta asocia
    al contacto.
    """

    for contact in contacts_array:

        if not isinstance(
            contact,
            dict,
        ):
            continue

        contact_wa_id = str(
            contact.get(
                "wa_id"
            )
            or ""
        ).strip()

        if contact_wa_id != wa_id:
            continue

        profile = contact.get(
            "profile",
            {},
        )

        if not isinstance(
            profile,
            dict,
        ):
            return ""

        return str(
            profile.get(
                "name"
            )
            or ""
        ).strip()

    return ""


# ==========================================================
# TIPO DE MENSAJE
# ==========================================================


def _map_message_type(
    meta_type: str,
) -> str:
    """
    Convierte el tipo técnico de Meta al tipo interno
    de MAO Comunicaciones.
    """

    tipos_soportados = {
        "text":
            Mensaje.TipoMensaje.TEXT,

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


def _map_status_type(
    meta_status: str,
):
    """
    Convierte los estados técnicos de Meta al dominio
    de transporte de MAO Comunicaciones.
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


def _extract_text(
    message: dict,
) -> str:
    """
    Extrae la representación textual principal del mensaje.

    La información estructurada adicional permanece en
    metadata para que otros sistemas puedan utilizarla
    posteriormente.
    """

    m_type = str(
        message.get(
            "type"
        )
        or ""
    ).strip().lower()

    # ======================================================
    # TEXTO
    # ======================================================

    if m_type == "text":

        data = message.get(
            "text",
            {},
        )

        if not isinstance(
            data,
            dict,
        ):
            return ""

        return str(
            data.get(
                "body"
            )
            or ""
        )

    # ======================================================
    # BOTÓN LEGACY
    # ======================================================

    if m_type == "button":

        data = message.get(
            "button",
            {},
        )

        if not isinstance(
            data,
            dict,
        ):
            return ""

        return str(
            data.get(
                "text"
            )
            or ""
        )

    # ======================================================
    # INTERACTIVE
    # ======================================================

    if m_type == "interactive":

        interactive = message.get(
            "interactive",
            {},
        )

        if not isinstance(
            interactive,
            dict,
        ):
            return ""

        button_reply = interactive.get(
            "button_reply",
            {},
        )

        if isinstance(
            button_reply,
            dict,
        ):

            title = button_reply.get(
                "title"
            )

            if title:
                return str(
                    title
                )

        list_reply = interactive.get(
            "list_reply",
            {},
        )

        if isinstance(
            list_reply,
            dict,
        ):

            title = list_reply.get(
                "title"
            )

            if title:
                return str(
                    title
                )

        return ""

    # ======================================================
    # CAPTION DE MULTIMEDIA
    # ======================================================

    if m_type in (
        "image",
        "video",
        "document",
    ):

        media = message.get(
            m_type,
            {},
        )

        if not isinstance(
            media,
            dict,
        ):
            return ""

        return str(
            media.get(
                "caption"
            )
            or ""
        )

    # ======================================================
    # REACCIÓN
    # ======================================================

    if m_type == "reaction":

        reaction = message.get(
            "reaction",
            {},
        )

        if not isinstance(
            reaction,
            dict,
        ):
            return ""

        return str(
            reaction.get(
                "emoji"
            )
            or ""
        )

    # ======================================================
    # DESCONOCIDO
    # ======================================================

    if m_type == "unknown":

        return (
            "Formato de mensaje de Meta no soportado."
        )

    return ""


# ==========================================================
# RESPUESTA / CONTEXTO
# ==========================================================


def _extract_reply_to(
    message: dict,
):
    """
    Obtiene el wamid del mensaje original cuando el
    mensaje actual es una respuesta.
    """

    context = message.get(
        "context",
        {},
    )

    if not isinstance(
        context,
        dict,
    ):
        return None

    external_id = str(
        context.get(
            "id"
        )
        or ""
    ).strip()

    return (
        external_id
        or None
    )


# ==========================================================
# MEDIA ID
# ==========================================================


def _extract_media_id(
    message: dict,
):
    """
    Extrae el media_id de mensajes que contienen
    multimedia.
    """

    m_type = str(
        message.get(
            "type"
        )
        or ""
    ).strip().lower()

    if m_type not in (
        "audio",
        "image",
        "video",
        "document",
        "sticker",
    ):
        return None

    media = message.get(
        m_type,
        {},
    )

    if not isinstance(
        media,
        dict,
    ):
        return None

    media_id = str(
        media.get(
            "id"
        )
        or ""
    ).strip()

    return (
        media_id
        or None
    )


# ==========================================================
# MIME TYPE
# ==========================================================


def _extract_mime_type(
    message: dict,
):
    """
    Extrae el MIME type que Meta incluye en mensajes
    multimedia.
    """

    m_type = str(
        message.get(
            "type"
        )
        or ""
    ).strip().lower()

    if m_type not in (
        "audio",
        "image",
        "video",
        "document",
        "sticker",
    ):
        return None

    media = message.get(
        m_type,
        {},
    )

    if not isinstance(
        media,
        dict,
    ):
        return None

    mime_type = str(
        media.get(
            "mime_type"
        )
        or ""
    ).strip()

    return (
        mime_type
        or None
    )


# ==========================================================
# NOMBRE DEL ARCHIVO
# ==========================================================


def _extract_filename(
    message: dict,
):
    """
    Extrae el nombre original cuando Meta lo proporciona.

    Normalmente aplica principalmente a documentos.
    """

    m_type = str(
        message.get(
            "type"
        )
        or ""
    ).strip().lower()

    if m_type != "document":
        return None

    document = message.get(
        "document",
        {},
    )

    if not isinstance(
        document,
        dict,
    ):
        return None

    filename = str(
        document.get(
            "filename"
        )
        or ""
    ).strip()

    return (
        filename
        or None
    )


# ==========================================================
# ERROR DE STATUS
# ==========================================================


def _extract_status_error(
    status: dict,
):
    """
    Extrae el primer error técnico reportado por Meta
    para un estado FALLIDO.

    Retorna:

        (
            error_codigo,
            error_detalle,
        )
    """

    errors = status.get(
        "errors",
        [],
    )

    if not isinstance(
        errors,
        list,
    ) or not errors:

        return (
            None,
            None,
        )

    error = errors[0]

    if not isinstance(
        error,
        dict,
    ):

        return (
            None,
            str(error),
        )

    codigo = (
        error.get(
            "code"
        )
        or error.get(
            "error_subcode"
        )
    )

    detalle = (
        error.get(
            "message"
        )
        or error.get(
            "title"
        )
    )

    # Algunos errores de Meta contienen más información
    # en error_data.details.
    error_data = error.get(
        "error_data",
        {},
    )

    if isinstance(
        error_data,
        dict,
    ):

        details = error_data.get(
            "details"
        )

        if details:
            detalle = (
                str(details)
                if not detalle
                else f"{detalle}: {details}"
            )

    return (
        (
            str(codigo)
            if codigo is not None
            else None
        ),
        (
            str(detalle)
            if detalle
            else None
        ),
    )


# ==========================================================
# METADATA DEL MENSAJE
# ==========================================================


def _extract_message_metadata(
    *,
    message: dict,
    meta_type: str,
    display_phone_number: str,
):
    """
    Conserva datos técnicos que pueden ser importantes
    posteriormente para MAO Citas, MAO Asistente u otros
    consumidores.

    MAO Comunicaciones los almacena, pero no interpreta
    su significado empresarial.
    """

    metadata = {
        "meta_type":
            meta_type,
    }

    if display_phone_number:

        metadata[
            "display_phone_number"
        ] = display_phone_number

    # ======================================================
    # CONTEXTO
    # ======================================================

    context = message.get(
        "context"
    )

    if isinstance(
        context,
        dict,
    ):

        metadata[
            "context"
        ] = context

    # ======================================================
    # UBICACIÓN
    # ======================================================

    if meta_type == "location":

        location = message.get(
            "location"
        )

        if isinstance(
            location,
            dict,
        ):

            metadata[
                "location"
            ] = location

    # ======================================================
    # CONTACTOS
    # ======================================================

    if meta_type == "contacts":

        contacts = message.get(
            "contacts"
        )

        if isinstance(
            contacts,
            list,
        ):

            metadata[
                "contacts"
            ] = contacts

    # ======================================================
    # INTERACTIVE
    # ======================================================

    if meta_type == "interactive":

        interactive = message.get(
            "interactive"
        )

        if isinstance(
            interactive,
            dict,
        ):

            metadata[
                "interactive"
            ] = interactive

    # ======================================================
    # BOTÓN
    # ======================================================

    if meta_type == "button":

        button = message.get(
            "button"
        )

        if isinstance(
            button,
            dict,
        ):

            metadata[
                "button"
            ] = button

    # ======================================================
    # REACCIÓN
    # ======================================================

    if meta_type == "reaction":

        reaction = message.get(
            "reaction"
        )

        if isinstance(
            reaction,
            dict,
        ):

            metadata[
                "reaction"
            ] = reaction

    return metadata


# ==========================================================
# METADATA DEL STATUS
# ==========================================================


def _extract_status_metadata(
    *,
    status: dict,
    meta_status: str,
    display_phone_number: str,
):
    """
    Conserva información técnica adicional de estados
    enviados por Meta.
    """

    metadata = {
        "meta_status":
            meta_status,
    }

    if display_phone_number:

        metadata[
            "display_phone_number"
        ] = display_phone_number

    conversation = status.get(
        "conversation"
    )

    if isinstance(
        conversation,
        dict,
    ):

        metadata[
            "conversation"
        ] = conversation

    pricing = status.get(
        "pricing"
    )

    if isinstance(
        pricing,
        dict,
    ):

        metadata[
            "pricing"
        ] = pricing

    return metadata