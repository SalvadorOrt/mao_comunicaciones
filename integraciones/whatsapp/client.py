# integraciones/whatsapp/client.py

import logging
from typing import Optional

import requests
from django.conf import settings


logger = logging.getLogger(__name__)


# ==========================================================
# META GRAPH API
# ==========================================================

GRAPH_API_BASE_URL = "https://graph.facebook.com"


# ==========================================================
# EXCEPCIONES INTERNAS
# ==========================================================


class MetaClientError(Exception):
    """
    Excepción base del cliente técnico de Meta.
    """

    pass


class MetaClientNoConfigurado(MetaClientError):
    """
    Falta configuración necesaria para utilizar Meta.
    """

    pass


# ==========================================================
# CONFIGURACIÓN
# ==========================================================


def get_meta_api_version() -> str:
    """
    Obtiene la versión de Graph API configurada.

    La versión debe configurarse externamente para evitar
    que MAO Comunicaciones dependa de una versión fija
    escrita en código.
    """

    version = str(
        getattr(
            settings,
            "META_API_VERSION",
            "",
        )
        or ""
    ).strip()

    if not version:
        raise MetaClientNoConfigurado(
            "META_API_VERSION no está configurado."
        )

    if not version.startswith("v"):
        version = f"v{version}"

    return version


def get_global_access_token() -> str:
    """
    Obtiene el token técnico utilizado por MAO Comunicaciones
    para comunicarse con WhatsApp Cloud API.

    Ningún ERP, MAO Citas ni MAO Asistente necesita conocer
    este token.
    """

    token = str(
        getattr(
            settings,
            "META_ACCESS_TOKEN",
            "",
        )
        or ""
    ).strip()

    if not token:
        raise MetaClientNoConfigurado(
            "META_ACCESS_TOKEN no está configurado."
        )

    return token


def _resolver_token(
    access_token: Optional[str] = None,
) -> str:
    """
    Permite inyectar un token explícito en tests y,
    normalmente, utiliza la configuración global.
    """

    token = str(
        access_token or ""
    ).strip()

    if token:
        return token

    return get_global_access_token()


def _build_url(
    endpoint: str,
) -> str:
    """
    Construye una URL de Graph API.
    """

    version = get_meta_api_version()

    endpoint = str(
        endpoint or ""
    ).strip().lstrip("/")

    if not endpoint:
        raise ValueError(
            "Se requiere un endpoint de Meta."
        )

    return (
        f"{GRAPH_API_BASE_URL}/"
        f"{version}/"
        f"{endpoint}"
    )


# ==========================================================
# RESPUESTAS
# ==========================================================


def _respuesta_error(
    *,
    tipo: str,
    detalle: Optional[str] = None,
    status_code: Optional[int] = None,
    codigo=None,
    raw_response=None,
) -> dict:
    """
    Contrato uniforme de error utilizado por el cliente.

    Nunca incluye access tokens.
    """

    error = {
        "type": tipo,
    }

    if detalle:
        error["message"] = str(
            detalle
        )

    if status_code is not None:
        error["status_code"] = (
            status_code
        )

    if codigo is not None:
        error["code"] = codigo

    return {
        "success": False,
        "error": error,
        "raw_response": raw_response,
    }


def _extraer_error_meta(
    response: requests.Response,
):
    """
    Extrae información útil de un error HTTP de Meta
    sin depender de que siempre exista JSON válido.
    """

    raw = None
    codigo = None
    detalle = None

    try:

        raw = response.json()

        if isinstance(raw, dict):

            error = raw.get(
                "error"
            )

            if isinstance(error, dict):

                codigo = (
                    error.get("code")
                    or error.get(
                        "error_subcode"
                    )
                )

                detalle = (
                    error.get("message")
                    or error.get(
                        "error_user_msg"
                    )
                )

    except ValueError:
        raw = None

    if not detalle:

        try:
            detalle = (
                response.text
                or "Meta devolvió un error HTTP."
            )

        except Exception:
            detalle = (
                "Meta devolvió un error HTTP."
            )

    return (
        codigo,
        detalle,
        raw,
    )


def _obtener_wamid(
    data: dict,
):
    """
    Extrae el identificador wamid devuelto por Meta.
    """

    if not isinstance(
        data,
        dict,
    ):
        return None

    messages = data.get(
        "messages"
    )

    if (
        not isinstance(
            messages,
            list,
        )
        or not messages
    ):
        return None

    primer_mensaje = messages[0]

    if not isinstance(
        primer_mensaje,
        dict,
    ):
        return None

    return primer_mensaje.get(
        "id"
    )


# ==========================================================
# REQUEST JSON
# ==========================================================


def _post_json(
    *,
    url: str,
    payload: dict,
    access_token: Optional[str] = None,
    timeout=(3.0, 10.0),
) -> dict:
    """
    Ejecuta una solicitud POST JSON contra Meta.

    Es una utilidad de transporte puro.
    """

    try:
        token = _resolver_token(
            access_token
        )

    except MetaClientNoConfigurado as exc:

        logger.error(
            "Meta no está configurado correctamente."
        )

        return _respuesta_error(
            tipo="configuration_error",
            detalle=str(exc),
        )

    headers = {
        "Authorization":
            f"Bearer {token}",

        "Content-Type":
            "application/json",

        "Accept":
            "application/json",
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )

    except requests.Timeout:

        logger.warning(
            "Timeout comunicándose con Meta."
        )

        return _respuesta_error(
            tipo="timeout",
            detalle=(
                "Meta tardó demasiado en responder."
            ),
        )

    except requests.RequestException:

        logger.exception(
            "Error de red comunicándose con Meta."
        )

        return _respuesta_error(
            tipo="network_error",
            detalle=(
                "No fue posible comunicarse con Meta."
            ),
        )

    # ======================================================
    # ERROR HTTP
    # ======================================================

    if not response.ok:

        (
            codigo,
            detalle,
            raw,
        ) = _extraer_error_meta(
            response
        )

        logger.warning(
            "Meta respondió HTTP %s.",
            response.status_code,
        )

        return _respuesta_error(
            tipo="http_error",
            detalle=detalle,
            status_code=response.status_code,
            codigo=codigo,
            raw_response=raw,
        )

    # ======================================================
    # JSON
    # ======================================================

    try:
        data = response.json()

    except ValueError:

        logger.error(
            "Meta respondió correctamente pero "
            "el cuerpo no contiene JSON válido."
        )

        return _respuesta_error(
            tipo="invalid_json",
            detalle=(
                "Meta devolvió una respuesta "
                "JSON inválida."
            ),
            status_code=response.status_code,
        )

    return {
        "success": True,
        "raw_response": data,
    }


# ==========================================================
# ENVIAR MENSAJE GENÉRICO
# ==========================================================


def enviar_payload_mensaje_meta(
    *,
    phone_number_id: str,
    wa_id: str,
    tipo: str,
    contenido: dict,
    access_token: Optional[str] = None,
) -> dict:
    """
    Envía un payload de mensaje mediante WhatsApp Cloud API.

    Esta función constituye el transporte genérico para:

        TEXT
        DOCUMENT
        IMAGE
        VIDEO
        AUDIO
        etc.

    No contiene ninguna lógica de ERP, citas o IA.
    """

    phone_number_id = str(
        phone_number_id or ""
    ).strip()

    wa_id = str(
        wa_id or ""
    ).strip()

    tipo = str(
        tipo or ""
    ).strip().lower()

    if not phone_number_id:

        return _respuesta_error(
            tipo="validation_error",
            detalle=(
                "Falta phone_number_id."
            ),
        )

    if not wa_id:

        return _respuesta_error(
            tipo="validation_error",
            detalle="Falta wa_id.",
        )

    if not tipo:

        return _respuesta_error(
            tipo="validation_error",
            detalle=(
                "Falta el tipo de mensaje."
            ),
        )

    if not isinstance(
        contenido,
        dict,
    ):

        return _respuesta_error(
            tipo="validation_error",
            detalle=(
                "El contenido del mensaje "
                "no es válido."
            ),
        )

    try:

        url = _build_url(
            f"{phone_number_id}/messages"
        )

    except (
        MetaClientNoConfigurado,
        ValueError,
    ) as exc:

        return _respuesta_error(
            tipo="configuration_error",
            detalle=str(exc),
        )

    payload = {
        "messaging_product":
            "whatsapp",

        "recipient_type":
            "individual",

        "to":
            wa_id,

        "type":
            tipo,

        tipo:
            contenido,
    }

    resultado = _post_json(
        url=url,
        payload=payload,
        access_token=access_token,
        timeout=(
            3.0,
            10.0,
        ),
    )

    if resultado.get(
        "success"
    ) is not True:

        return resultado

    data = resultado.get(
        "raw_response"
    )

    wamid = _obtener_wamid(
        data
    )

    if not wamid:

        return _respuesta_error(
            tipo="missing_wamid",
            detalle=(
                "Meta aceptó el mensaje pero "
                "no devolvió wamid."
            ),
            raw_response=data,
        )

    return {
        "success": True,
        "wamid": wamid,
        "raw_response": data,
    }


# ==========================================================
# TEXTO
# ==========================================================


def enviar_mensaje_texto_meta(
    phone_number_id: str,
    wa_id: str,
    text: str,
    access_token: Optional[str] = None,
) -> dict:
    """
    Envía un mensaje de texto.

    El destinatario proviene de la identidad WhatsApp
    almacenada por MAO Comunicaciones.
    """

    text = str(
        text or ""
    ).strip()

    if not text:

        return _respuesta_error(
            tipo="validation_error",
            detalle=(
                "No se puede enviar "
                "un mensaje vacío."
            ),
        )

    return enviar_payload_mensaje_meta(
        phone_number_id=phone_number_id,
        wa_id=wa_id,
        tipo="text",
        contenido={
            "preview_url": False,
            "body": text,
        },
        access_token=access_token,
    )


# ==========================================================
# SUBIR MULTIMEDIA
# ==========================================================


def subir_media_meta(
    phone_number_id: str,
    archivo_bytes: bytes,
    nombre_archivo: str,
    mime_type: str,
    access_token: Optional[str] = None,
) -> dict:
    """
    Sube multimedia a WhatsApp Cloud API.

    Esta función es genérica y puede utilizarse para:

        PDF
        imágenes
        audio
        video
        documentos
    """

    phone_number_id = str(
        phone_number_id or ""
    ).strip()

    nombre_archivo = str(
        nombre_archivo or ""
    ).strip()

    mime_type = str(
        mime_type or ""
    ).strip()

    if not phone_number_id:

        return _respuesta_error(
            tipo="validation_error",
            detalle=(
                "Falta phone_number_id."
            ),
        )

    if not isinstance(
        archivo_bytes,
        (
            bytes,
            bytearray,
        ),
    ):

        return _respuesta_error(
            tipo="validation_error",
            detalle=(
                "El contenido del archivo "
                "no es binario."
            ),
        )

    archivo_bytes = bytes(
        archivo_bytes
    )

    if not archivo_bytes:

        return _respuesta_error(
            tipo="validation_error",
            detalle=(
                "El archivo está vacío."
            ),
        )

    if not nombre_archivo:

        return _respuesta_error(
            tipo="validation_error",
            detalle=(
                "Falta nombre_archivo."
            ),
        )

    if not mime_type:

        return _respuesta_error(
            tipo="validation_error",
            detalle="Falta mime_type.",
        )

    try:

        token = _resolver_token(
            access_token
        )

        url = _build_url(
            f"{phone_number_id}/media"
        )

    except (
        MetaClientNoConfigurado,
        ValueError,
    ) as exc:

        return _respuesta_error(
            tipo="configuration_error",
            detalle=str(exc),
        )

    headers = {
        "Authorization":
            f"Bearer {token}",

        "Accept":
            "application/json",
    }

    data = {
        "messaging_product":
            "whatsapp",
    }

    files = {
        "file": (
            nombre_archivo,
            archivo_bytes,
            mime_type,
        ),
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            data=data,
            files=files,
            timeout=(
                5.0,
                30.0,
            ),
        )

    except requests.Timeout:

        logger.warning(
            "Timeout subiendo multimedia a Meta."
        )

        return _respuesta_error(
            tipo="timeout",
            detalle=(
                "Meta tardó demasiado en "
                "recibir el archivo."
            ),
        )

    except requests.RequestException:

        logger.exception(
            "Error de red subiendo multimedia a Meta."
        )

        return _respuesta_error(
            tipo="network_error",
            detalle=(
                "No fue posible subir "
                "el archivo a Meta."
            ),
        )

    if not response.ok:

        (
            codigo,
            detalle,
            raw,
        ) = _extraer_error_meta(
            response
        )

        return _respuesta_error(
            tipo="http_error",
            detalle=detalle,
            status_code=response.status_code,
            codigo=codigo,
            raw_response=raw,
        )

    try:
        response_data = response.json()

    except ValueError:

        return _respuesta_error(
            tipo="invalid_json",
            detalle=(
                "Meta devolvió una respuesta "
                "inválida al subir multimedia."
            ),
            status_code=response.status_code,
        )

    media_id = str(
        response_data.get(
            "id"
        )
        or ""
    ).strip()

    if not media_id:

        return _respuesta_error(
            tipo="missing_media_id",
            detalle=(
                "Meta recibió el archivo pero "
                "no devolvió media_id."
            ),
            raw_response=response_data,
        )

    logger.info(
        "Multimedia subida correctamente a Meta."
    )

    return {
        "success": True,
        "media_id": media_id,
        "raw_response": response_data,
    }


# ==========================================================
# DOCUMENTO PDF
# ==========================================================


def subir_documento_pdf_meta(
    phone_number_id: str,
    pdf_bytes: bytes,
    nombre_archivo: str,
    access_token: Optional[str] = None,
) -> dict:
    """
    Atajo para subir un PDF.
    """

    return subir_media_meta(
        phone_number_id=phone_number_id,
        archivo_bytes=pdf_bytes,
        nombre_archivo=nombre_archivo,
        mime_type="application/pdf",
        access_token=access_token,
    )


# ==========================================================
# ENVIAR DOCUMENTO
# ==========================================================


def enviar_documento_meta(
    phone_number_id: str,
    wa_id: str,
    media_id: str,
    nombre_archivo: str,
    caption: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict:
    """
    Envía un documento previamente subido a Meta.
    """

    media_id = str(
        media_id or ""
    ).strip()

    nombre_archivo = str(
        nombre_archivo or ""
    ).strip()

    caption = str(
        caption or ""
    ).strip()

    if not media_id:

        return _respuesta_error(
            tipo="validation_error",
            detalle="Falta media_id.",
        )

    if not nombre_archivo:

        return _respuesta_error(
            tipo="validation_error",
            detalle=(
                "Falta nombre_archivo."
            ),
        )

    documento = {
        "id": media_id,
        "filename": nombre_archivo,
    }

    if caption:

        documento[
            "caption"
        ] = caption

    resultado = enviar_payload_mensaje_meta(
        phone_number_id=phone_number_id,
        wa_id=wa_id,
        tipo="document",
        contenido=documento,
        access_token=access_token,
    )

    if resultado.get(
        "success"
    ) is True:

        resultado[
            "media_id"
        ] = media_id

    return resultado


# ==========================================================
# IMAGEN
# ==========================================================


def enviar_imagen_meta(
    phone_number_id: str,
    wa_id: str,
    media_id: str,
    caption: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict:
    """
    Envía una imagen previamente subida.
    """

    media_id = str(
        media_id or ""
    ).strip()

    if not media_id:

        return _respuesta_error(
            tipo="validation_error",
            detalle="Falta media_id.",
        )

    contenido = {
        "id": media_id,
    }

    caption = str(
        caption or ""
    ).strip()

    if caption:
        contenido["caption"] = caption

    resultado = enviar_payload_mensaje_meta(
        phone_number_id=phone_number_id,
        wa_id=wa_id,
        tipo="image",
        contenido=contenido,
        access_token=access_token,
    )

    if resultado.get("success") is True:
        resultado["media_id"] = media_id

    return resultado


# ==========================================================
# VIDEO
# ==========================================================


def enviar_video_meta(
    phone_number_id: str,
    wa_id: str,
    media_id: str,
    caption: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict:
    """
    Envía un video previamente subido.
    """

    media_id = str(
        media_id or ""
    ).strip()

    if not media_id:

        return _respuesta_error(
            tipo="validation_error",
            detalle="Falta media_id.",
        )

    contenido = {
        "id": media_id,
    }

    caption = str(
        caption or ""
    ).strip()

    if caption:
        contenido["caption"] = caption

    resultado = enviar_payload_mensaje_meta(
        phone_number_id=phone_number_id,
        wa_id=wa_id,
        tipo="video",
        contenido=contenido,
        access_token=access_token,
    )

    if resultado.get("success") is True:
        resultado["media_id"] = media_id

    return resultado


# ==========================================================
# AUDIO
# ==========================================================


def enviar_audio_meta(
    phone_number_id: str,
    wa_id: str,
    media_id: str,
    access_token: Optional[str] = None,
) -> dict:
    """
    Envía audio previamente subido.
    """

    media_id = str(
        media_id or ""
    ).strip()

    if not media_id:

        return _respuesta_error(
            tipo="validation_error",
            detalle="Falta media_id.",
        )

    resultado = enviar_payload_mensaje_meta(
        phone_number_id=phone_number_id,
        wa_id=wa_id,
        tipo="audio",
        contenido={
            "id": media_id,
        },
        access_token=access_token,
    )

    if resultado.get("success") is True:
        resultado["media_id"] = media_id

    return resultado


# ==========================================================
# SUBIR + ENVIAR PDF
# ==========================================================


def enviar_pdf_meta(
    phone_number_id: str,
    wa_id: str,
    pdf_bytes: bytes,
    nombre_archivo: str,
    caption: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict:
    """
    Flujo técnico completo:

        PDF
          ↓
        upload Meta
          ↓
        media_id
          ↓
        send document
          ↓
        wamid

    No conoce ERP, Citas ni Asistente.
    """

    resultado_subida = (
        subir_documento_pdf_meta(
            phone_number_id=phone_number_id,
            pdf_bytes=pdf_bytes,
            nombre_archivo=nombre_archivo,
            access_token=access_token,
        )
    )

    if (
        resultado_subida.get(
            "success"
        )
        is not True
    ):

        return {
            "success": False,
            "error": {
                "type":
                    "media_upload_failed",

                "message":
                    "No fue posible subir "
                    "el PDF a Meta.",
            },
            "upload_result":
                resultado_subida,
        }

    media_id = resultado_subida[
        "media_id"
    ]

    resultado_envio = (
        enviar_documento_meta(
            phone_number_id=phone_number_id,
            wa_id=wa_id,
            media_id=media_id,
            nombre_archivo=nombre_archivo,
            caption=caption,
            access_token=access_token,
        )
    )

    if (
        resultado_envio.get(
            "success"
        )
        is not True
    ):

        return {
            "success": False,
            "error": {
                "type":
                    "document_send_failed",

                "message":
                    "El PDF fue subido pero "
                    "no pudo enviarse.",
            },
            "media_id":
                media_id,
            "upload_result":
                resultado_subida,
            "send_result":
                resultado_envio,
        }

    return {
        "success": True,
        "media_id": media_id,
        "wamid": resultado_envio.get(
            "wamid"
        ),
        "upload_result":
            resultado_subida,
        "send_result":
            resultado_envio,
    }


# ==========================================================
# OBTENER URL DE MULTIMEDIA
# ==========================================================


def obtener_url_descarga_media(
    media_id: str,
    access_token: Optional[str] = None,
) -> Optional[str]:
    """
    Obtiene la URL temporal de descarga asociada
    a un media_id de Meta.
    """

    media_id = str(
        media_id or ""
    ).strip()

    if not media_id:
        return None

    try:

        token = _resolver_token(
            access_token
        )

        url = _build_url(
            media_id
        )

    except (
        MetaClientNoConfigurado,
        ValueError,
    ):

        logger.exception(
            "No fue posible preparar la consulta de media."
        )

        return None

    headers = {
        "Authorization":
            f"Bearer {token}",

        "Accept":
            "application/json",
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=(
                3.0,
                7.0,
            ),
        )

    except requests.RequestException:

        logger.exception(
            "Error de red obteniendo URL de multimedia."
        )

        return None

    if not response.ok:

        logger.warning(
            "Meta rechazó consulta de multimedia HTTP %s.",
            response.status_code,
        )

        return None

    try:
        data = response.json()

    except ValueError:

        logger.error(
            "Meta devolvió JSON inválido "
            "consultando multimedia."
        )

        return None

    media_url = data.get(
        "url"
    )

    if not media_url:
        return None

    return str(
        media_url
    ).strip()


# ==========================================================
# DESCARGAR ARCHIVO
# ==========================================================


def descargar_archivo_fisico(
    media_url: str,
    access_token: Optional[str] = None,
):
    """
    Descarga bytes desde una URL temporal de Meta.

    Retorna:

        (
            bytes_content,
            mime_type,
        )

    En caso de fallo:

        (None, None)
    """

    media_url = str(
        media_url or ""
    ).strip()

    if not media_url:
        return (
            None,
            None,
        )

    try:
        token = _resolver_token(
            access_token
        )

    except MetaClientNoConfigurado:

        logger.exception(
            "Meta no está configurado "
            "para descargar multimedia."
        )

        return (
            None,
            None,
        )

    headers = {
        "Authorization":
            f"Bearer {token}",
    }

    try:

        response = requests.get(
            media_url,
            headers=headers,
            timeout=(
                3.0,
                30.0,
            ),
        )

    except requests.RequestException:

        logger.exception(
            "Error descargando multimedia desde Meta."
        )

        return (
            None,
            None,
        )

    if not response.ok:

        logger.warning(
            "Meta rechazó descarga multimedia HTTP %s.",
            response.status_code,
        )

        return (
            None,
            None,
        )

    mime_type = (
        response.headers.get(
            "Content-Type"
        )
        or
        "application/octet-stream"
    )

    return (
        response.content,
        mime_type,
    )