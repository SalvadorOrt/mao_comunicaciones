# integraciones/whatsapp/client.py

import logging

import requests
from django.conf import settings


logger = logging.getLogger("django")


# ==========================================================
# META GRAPH API
# ==========================================================

GRAPH_API_BASE_URL = "https://graph.facebook.com/"


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

def get_meta_api_version() -> str:
    """
    Obtiene la versión de Meta Graph API configurada.

    Si no existe META_API_VERSION en settings,
    utiliza v20.0 como valor por defecto.
    """

    return getattr(
        settings,
        "META_API_VERSION",
        "v20.0",
    )


def get_global_access_token() -> str:
    """
    Obtiene el token global utilizado para comunicarse
    con Meta WhatsApp Cloud API.
    """

    return getattr(
        settings,
        "META_ACCESS_TOKEN",
        None,
    )


def _build_url(endpoint: str) -> str:
    """
    Construye una URL completa de Meta Graph API.
    """

    version = get_meta_api_version()

    clean_endpoint = endpoint.lstrip("/")

    return (
        f"{GRAPH_API_BASE_URL}"
        f"{version}/"
        f"{clean_endpoint}"
    )


# ==========================================================
# UTILIDADES INTERNAS
# ==========================================================

def _obtener_wamid(data: dict):
    """
    Extrae el identificador del mensaje generado por Meta.

    Ejemplo:

        wamid.HBgM...
    """

    if not isinstance(data, dict):
        return None

    messages = data.get(
        "messages",
        [],
    )

    if not messages:
        return None

    return messages[0].get("id")


# ==========================================================
# ENVIAR MENSAJE DE TEXTO
# ==========================================================

def enviar_mensaje_texto_meta(
    phone_number_id: str,
    wa_id: str,
    text: str,
    access_token: str = None,
) -> dict:
    """
    Envía un mensaje de texto utilizando WhatsApp Cloud API.

    phone_number_id:
        Número emisor configurado en Meta para MAO.

    wa_id:
        Número destinatario.

        Ejemplo Ecuador:
            593991234567

        Este número vendrá del ERP.

    text:
        Texto que se enviará al cliente.
    """

    token = (
        access_token
        or get_global_access_token()
    )

    if not token:
        logger.error(
            "No se ha configurado un META_ACCESS_TOKEN. "
            "Envío abortado."
        )

        return {
            "error": "Missing access token",
        }

    if not phone_number_id:
        return {
            "error": "Missing phone_number_id",
        }

    if not wa_id:
        return {
            "error": "Missing wa_id",
        }

    if not text:
        return {
            "error": "Missing text",
        }

    url = _build_url(
        f"{phone_number_id}/messages"
    )

    headers = {
        "Authorization":
            f"Bearer {token}",

        "Content-Type":
            "application/json",
    }

    payload = {
        "messaging_product":
            "whatsapp",

        "recipient_type":
            "individual",

        "to":
            wa_id,

        "type":
            "text",

        "text": {
            "preview_url": False,
            "body": text,
        },
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=(
                3.0,
                5.0,
            ),
        )

        response.raise_for_status()

        data = response.json()

        wamid = _obtener_wamid(
            data
        )

        return {
            "success": True,
            "wamid": wamid,
            "raw_response": data,
        }

    except requests.exceptions.HTTPError as http_err:

        details = (
            http_err.response.text
            if http_err.response is not None
            else str(http_err)
        )

        logger.error(
            "Error HTTP enviando mensaje a Meta "
            "(%s -> %s): %s",
            phone_number_id,
            wa_id,
            details,
        )

        return {
            "error": "HTTP Error",
            "details": details,
        }

    except requests.exceptions.RequestException as req_err:

        logger.error(
            "Error de red/Timeout enviando mensaje "
            "a Meta: %s",
            req_err,
        )

        return {
            "error": "Network Error",
            "details": str(req_err),
        }

    except ValueError as json_err:

        logger.error(
            "Error decodificando respuesta JSON "
            "de Meta: %s",
            json_err,
        )

        return {
            "error": "JSON Parse Error",
            "details": str(json_err),
        }


# ==========================================================
# SUBIR ARCHIVO / MEDIA A META
# ==========================================================

def subir_media_meta(
    phone_number_id: str,
    archivo_bytes: bytes,
    nombre_archivo: str,
    mime_type: str,
    access_token: str = None,
) -> dict:
    """
    Sube un archivo a WhatsApp Cloud API.

    Devuelve el media_id generado por Meta.

    Este método puede utilizarse posteriormente para:
    - PDF
    - imágenes
    - audio
    - otros tipos admitidos por WhatsApp.

    Para nuestra ficha técnica:

        mime_type = application/pdf
    """

    token = (
        access_token
        or get_global_access_token()
    )

    # ======================================================
    # VALIDACIONES
    # ======================================================

    if not token:
        logger.error(
            "No se ha configurado META_ACCESS_TOKEN "
            "para subir multimedia."
        )

        return {
            "error": "Missing access token",
        }

    if not phone_number_id:
        return {
            "error": "Missing phone_number_id",
        }

    if not archivo_bytes:
        return {
            "error": "Missing file content",
        }

    if not nombre_archivo:
        return {
            "error": "Missing filename",
        }

    if not mime_type:
        return {
            "error": "Missing mime type",
        }

    # ======================================================
    # URL
    # ======================================================

    url = _build_url(
        f"{phone_number_id}/media"
    )

    # ======================================================
    # HEADERS
    # ======================================================
    #
    # IMPORTANTE:
    #
    # No ponemos Content-Type manualmente porque requests
    # construye automáticamente multipart/form-data y su
    # boundary.
    # ======================================================

    headers = {
        "Authorization":
            f"Bearer {token}",
    }

    # ======================================================
    # FORM DATA
    # ======================================================

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

    # ======================================================
    # REQUEST
    # ======================================================

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

        response.raise_for_status()

        response_data = (
            response.json()
        )

        media_id = response_data.get(
            "id"
        )

        if not media_id:

            logger.error(
                "Meta respondió correctamente al subir "
                "el archivo, pero no devolvió media_id."
            )

            return {
                "error": "Missing media_id",
                "raw_response": response_data,
            }

        logger.info(
            "Archivo subido correctamente a Meta. "
            "phone_number_id=%s media_id=%s "
            "filename=%s",
            phone_number_id,
            media_id,
            nombre_archivo,
        )

        return {
            "success": True,
            "media_id": media_id,
            "raw_response": response_data,
        }

    except requests.exceptions.HTTPError as http_err:

        details = (
            http_err.response.text
            if http_err.response is not None
            else str(http_err)
        )

        logger.error(
            "Error HTTP subiendo archivo a Meta "
            "(phone_number_id=%s, filename=%s): %s",
            phone_number_id,
            nombre_archivo,
            details,
        )

        return {
            "error": "HTTP Error",
            "details": details,
        }

    except requests.exceptions.RequestException as req_err:

        logger.error(
            "Error de red/Timeout subiendo archivo "
            "a Meta: %s",
            req_err,
        )

        return {
            "error": "Network Error",
            "details": str(req_err),
        }

    except ValueError as json_err:

        logger.error(
            "Error decodificando respuesta JSON "
            "al subir archivo a Meta: %s",
            json_err,
        )

        return {
            "error": "JSON Parse Error",
            "details": str(json_err),
        }


# ==========================================================
# SUBIR PDF
# ==========================================================

def subir_documento_pdf_meta(
    phone_number_id: str,
    pdf_bytes: bytes,
    nombre_archivo: str,
    access_token: str = None,
) -> dict:
    """
    Atajo específico para subir documentos PDF.

    Se utilizará para la ficha técnica enviada desde
    el ERP MAO.
    """

    return subir_media_meta(
        phone_number_id=phone_number_id,
        archivo_bytes=pdf_bytes,
        nombre_archivo=nombre_archivo,
        mime_type="application/pdf",
        access_token=access_token,
    )


# ==========================================================
# ENVIAR DOCUMENTO YA SUBIDO
# ==========================================================

def enviar_documento_meta(
    phone_number_id: str,
    wa_id: str,
    media_id: str,
    nombre_archivo: str,
    caption: str = None,
    access_token: str = None,
) -> dict:
    """
    Envía por WhatsApp un documento previamente subido
    a Meta.

    El documento debe estar identificado mediante media_id.

    wa_id:
        Número del cliente recibido desde el ERP.

    phone_number_id:
        Número corporativo MAO configurado en Meta.

    media_id:
        Identificador devuelto por subir_media_meta().
    """

    token = (
        access_token
        or get_global_access_token()
    )

    # ======================================================
    # VALIDACIONES
    # ======================================================

    if not token:
        logger.error(
            "No se ha configurado META_ACCESS_TOKEN "
            "para enviar documentos."
        )

        return {
            "error": "Missing access token",
        }

    if not phone_number_id:
        return {
            "error": "Missing phone_number_id",
        }

    if not wa_id:
        return {
            "error": "Missing wa_id",
        }

    if not media_id:
        return {
            "error": "Missing media_id",
        }

    if not nombre_archivo:
        return {
            "error": "Missing filename",
        }

    # ======================================================
    # URL
    # ======================================================

    url = _build_url(
        f"{phone_number_id}/messages"
    )

    # ======================================================
    # HEADERS
    # ======================================================

    headers = {
        "Authorization":
            f"Bearer {token}",

        "Content-Type":
            "application/json",
    }

    # ======================================================
    # DOCUMENTO
    # ======================================================

    documento = {
        "id":
            media_id,

        "filename":
            nombre_archivo,
    }

    if caption:
        documento["caption"] = caption

    # ======================================================
    # PAYLOAD
    # ======================================================

    payload = {
        "messaging_product":
            "whatsapp",

        "recipient_type":
            "individual",

        "to":
            wa_id,

        "type":
            "document",

        "document":
            documento,
    }

    # ======================================================
    # REQUEST
    # ======================================================

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=(
                3.0,
                10.0,
            ),
        )

        response.raise_for_status()

        data = response.json()

        wamid = _obtener_wamid(
            data
        )

        logger.info(
            "Documento enviado a Meta. "
            "phone_number_id=%s wa_id=%s "
            "media_id=%s wamid=%s",
            phone_number_id,
            wa_id,
            media_id,
            wamid,
        )

        return {
            "success": True,
            "wamid": wamid,
            "media_id": media_id,
            "raw_response": data,
        }

    except requests.exceptions.HTTPError as http_err:

        details = (
            http_err.response.text
            if http_err.response is not None
            else str(http_err)
        )

        logger.error(
            "Error HTTP enviando documento a Meta "
            "(%s -> %s): %s",
            phone_number_id,
            wa_id,
            details,
        )

        return {
            "error": "HTTP Error",
            "details": details,
        }

    except requests.exceptions.RequestException as req_err:

        logger.error(
            "Error de red/Timeout enviando "
            "documento a Meta: %s",
            req_err,
        )

        return {
            "error": "Network Error",
            "details": str(req_err),
        }

    except ValueError as json_err:

        logger.error(
            "Error decodificando respuesta JSON "
            "al enviar documento a Meta: %s",
            json_err,
        )

        return {
            "error": "JSON Parse Error",
            "details": str(json_err),
        }


# ==========================================================
# SUBIR + ENVIAR PDF
# ==========================================================

def enviar_pdf_meta(
    phone_number_id: str,
    wa_id: str,
    pdf_bytes: bytes,
    nombre_archivo: str,
    caption: str = None,
    access_token: str = None,
) -> dict:
    """
    Flujo completo para enviar un PDF:

        PDF
         ↓
        subir a Meta
         ↓
        media_id
         ↓
        enviar documento
         ↓
        wamid

    Esta será la función principal que utilizaremos
    posteriormente desde la integración ERP -> Asistente.
    """

    # ======================================================
    # 1. SUBIR PDF
    # ======================================================

    resultado_subida = (
        subir_documento_pdf_meta(
            phone_number_id=phone_number_id,
            pdf_bytes=pdf_bytes,
            nombre_archivo=nombre_archivo,
            access_token=access_token,
        )
    )

    if not resultado_subida.get(
        "success"
    ):
        return {
            "error": "Media upload failed",
            "upload_result":
                resultado_subida,
        }

    media_id = resultado_subida.get(
        "media_id"
    )

    # ======================================================
    # 2. ENVIAR DOCUMENTO
    # ======================================================

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

    if not resultado_envio.get(
        "success"
    ):
        return {
            "error": "Document send failed",
            "media_id": media_id,
            "upload_result":
                resultado_subida,
            "send_result":
                resultado_envio,
        }

    # ======================================================
    # RESULTADO
    # ======================================================

    return {
        "success": True,
        "media_id":
            media_id,

        "wamid":
            resultado_envio.get(
                "wamid"
            ),

        "upload_result":
            resultado_subida,

        "send_result":
            resultado_envio,
    }


# ==========================================================
# OBTENER URL DE DESCARGA DE MULTIMEDIA
# ==========================================================

def obtener_url_descarga_media(
    media_id: str,
    access_token: str = None,
) -> str:
    """
    Consulta a Meta Graph API por la URL temporal y segura
    asociada a un media_id.
    """

    token = (
        access_token
        or get_global_access_token()
    )

    if not token:
        logger.error(
            "No se ha configurado un META_ACCESS_TOKEN "
            "para descargar multimedia."
        )

        return None

    if not media_id:
        return None

    url = _build_url(
        media_id
    )

    headers = {
        "Authorization":
            f"Bearer {token}",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=(
                3.0,
                5.0,
            ),
        )

        response.raise_for_status()

        data = response.json()

        return data.get(
            "url"
        )

    except requests.exceptions.HTTPError as http_err:

        details = (
            http_err.response.text
            if http_err.response is not None
            else str(http_err)
        )

        logger.error(
            "Error HTTP obteniendo URL "
            "de media_id=%s: %s",
            media_id,
            details,
        )

        return None

    except requests.exceptions.RequestException as req_err:

        logger.error(
            "Error de red obteniendo URL "
            "de media_id=%s: %s",
            media_id,
            req_err,
        )

        return None

    except ValueError as json_err:

        logger.error(
            "Error decodificando respuesta JSON "
            "para media_id=%s: %s",
            media_id,
            json_err,
        )

        return None


# ==========================================================
# DESCARGAR ARCHIVO FÍSICO
# ==========================================================

def descargar_archivo_fisico(
    media_url: str,
    access_token: str = None,
) -> tuple:
    """
    Descarga físicamente un archivo desde la URL temporal
    proporcionada por Meta.

    Retorna:

        (
            bytes_content,
            mime_type,
        )
    """

    token = (
        access_token
        or get_global_access_token()
    )

    if not token:
        logger.error(
            "No se ha configurado META_ACCESS_TOKEN "
            "para descargar el archivo."
        )

        return None, None

    if not media_url:
        return None, None

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
                10.0,
            ),
        )

        response.raise_for_status()

        content = response.content

        mime_type = (
            response.headers.get(
                "Content-Type",
                "application/octet-stream",
            )
        )

        return (
            content,
            mime_type,
        )

    except requests.exceptions.HTTPError as http_err:

        details = (
            http_err.response.text
            if http_err.response is not None
            else str(http_err)
        )

        logger.error(
            "Error HTTP descargando archivo "
            "desde Meta: %s",
            details,
        )

        return None, None

    except requests.exceptions.RequestException as req_err:

        logger.error(
            "Error de red/Timeout descargando "
            "archivo desde Meta: %s",
            req_err,
        )

        return None, None