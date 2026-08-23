import hashlib
import hmac
import logging

from django.conf import settings


logger = logging.getLogger("django")


def validate_hub_signature(
    request_body: bytes,
    signature_header: str,
) -> bool:
    """
    Valida la autenticidad de un webhook de Meta Cloud API.

    Compara el HMAC-SHA256 calculado sobre request.body
    utilizando META_APP_SECRET contra la firma enviada
    por Meta en X-Hub-Signature-256.
    """

    meta_app_secret = getattr(
        settings,
        "META_APP_SECRET",
        None,
    )

    if not meta_app_secret:
        logger.error(
            "META_APP_SECRET no está configurado."
        )
        return False

    if (
        not signature_header
        or not signature_header.startswith("sha256=")
    ):
        logger.warning(
            "Cabecera X-Hub-Signature-256 "
            "ausente o inválida."
        )
        return False

    expected_hash = signature_header[7:]

    try:
        calculated_hmac = hmac.new(
            key=meta_app_secret.encode("utf-8"),
            msg=request_body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        is_valid = hmac.compare_digest(
            expected_hash,
            calculated_hmac,
        )

        if not is_valid:
            logger.warning(
                "La firma del webhook de Meta "
                "no coincide."
            )

        return is_valid

    except Exception:
        logger.exception(
            "Error interno validando la firma "
            "del webhook de Meta."
        )
        return False