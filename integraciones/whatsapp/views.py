# integraciones/whatsapp/views.py

import json
import logging
import secrets

from django.conf import settings
from django.http import (
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from integraciones.whatsapp.parser import (
    parse_whatsapp_payload,
)
from integraciones.whatsapp.services import (
    procesar_evento_webhook,
)
from integraciones.whatsapp.signature import (
    validate_hub_signature,
)


logger = logging.getLogger(__name__)


# ==========================================================
# WEBHOOK WHATSAPP
# ==========================================================


@csrf_exempt
@require_http_methods(
    [
        "GET",
        "POST",
    ]
)
def whatsapp_webhook_view(
    request,
):
    """
    Endpoint público utilizado por WhatsApp Cloud API.

    GET:
        Meta verifica que el webhook pertenece
        a MAO Comunicaciones.

    POST:
        Meta entrega mensajes y estados.

    Esta vista únicamente maneja HTTP y seguridad.

    La lógica de comunicación se delega a:

        parser.py
        services.py
        client.py
    """

    if request.method == "GET":

        return _verificar_webhook_meta(
            request
        )

    return _recibir_evento_meta(
        request
    )


# ==========================================================
# VERIFICACIÓN DEL WEBHOOK
# ==========================================================


def _verificar_webhook_meta(
    request,
):
    """
    Atiende la verificación inicial realizada por Meta.
    """

    mode = str(
        request.GET.get(
            "hub.mode"
        )
        or ""
    ).strip()

    token_recibido = str(
        request.GET.get(
            "hub.verify_token"
        )
        or ""
    ).strip()

    challenge = request.GET.get(
        "hub.challenge"
    )

    token_esperado = str(
        getattr(
            settings,
            "META_VERIFY_TOKEN",
            "",
        )
        or ""
    ).strip()

    # ======================================================
    # CONFIGURACIÓN
    # ======================================================

    if not token_esperado:

        logger.error(
            "META_VERIFY_TOKEN no está configurado."
        )

        return HttpResponseForbidden(
            "Webhook no configurado."
        )

    # ======================================================
    # VALIDACIÓN
    # ======================================================

    if (
        mode != "subscribe"
        or not token_recibido
        or not secrets.compare_digest(
            token_recibido,
            token_esperado,
        )
    ):

        logger.warning(
            (
                "Intento inválido de verificación "
                "del webhook de Meta."
            )
        )

        return HttpResponseForbidden(
            "Verificación inválida."
        )

    # ======================================================
    # CHALLENGE
    # ======================================================

    if challenge is None:

        return JsonResponse(
            {
                "status": "error",
                "message": "Missing challenge",
            },
            status=400,
        )

    logger.info(
        "Webhook de Meta verificado correctamente."
    )

    return HttpResponse(
        challenge,
        status=200,
    )


# ==========================================================
# RECEPCIÓN DE EVENTOS
# ==========================================================


def _recibir_evento_meta(
    request,
):
    """
    Recibe eventos enviados por Meta.

    Flujo:

        request.body
              ↓
        validar HMAC
              ↓
        JSON
              ↓
        parser
              ↓
        eventos normalizados
              ↓
        whatsapp/services.py
    """

    raw_body = request.body

    signature_header = (
        request.headers.get(
            "X-Hub-Signature-256",
            "",
        )
    )

    # ======================================================
    # FIRMA HMAC
    # ======================================================

    if not validate_hub_signature(
        raw_body,
        signature_header,
    ):

        logger.warning(
            (
                "Webhook de Meta rechazado "
                "por firma inválida."
            )
        )

        return HttpResponseForbidden(
            "Firma inválida."
        )

    # ======================================================
    # JSON
    # ======================================================

    try:

        payload = json.loads(
            raw_body.decode(
                "utf-8"
            )
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):

        logger.warning(
            "Meta envió JSON inválido."
        )

        return JsonResponse(
            {
                "status": "error",
                "message": "Invalid JSON",
            },
            status=400,
        )

    if not isinstance(
        payload,
        dict,
    ):

        return JsonResponse(
            {
                "status": "error",
                "message": "Invalid payload",
            },
            status=400,
        )

    # ======================================================
    # PARSER
    # ======================================================

    try:

        eventos = parse_whatsapp_payload(
            payload
        )

    except Exception:

        logger.exception(
            (
                "Error normalizando payload "
                "de WhatsApp."
            )
        )

        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Payload parsing error"
                ),
            },
            status=500,
        )

    if eventos is None:
        eventos = []

    # ======================================================
    # PROCESAR
    # ======================================================

    try:

        for evento in eventos:

            procesar_evento_webhook(
                evento
            )

    except Exception:

        logger.exception(
            (
                "Error procesando evento "
                "del webhook de WhatsApp."
            )
        )

        # Respondemos 500 para que Meta pueda reintentar.
        #
        # Los mensajes utilizan idempotencia mediante
        # external_id, por lo que un reintento no debería
        # duplicar el mismo mensaje.
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Webhook processing error"
                ),
            },
            status=500,
        )

    # ======================================================
    # OK
    # ======================================================

    return HttpResponse(
        "EVENT_RECEIVED",
        status=200,
    )