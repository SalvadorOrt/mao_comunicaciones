# integraciones/whatsapp/signature.py

import hashlib
import hmac
import logging

from django.conf import settings


logger = logging.getLogger(__name__)


# ==========================================================
# VALIDACIÓN DE FIRMA META
# ==========================================================


def validate_hub_signature(
    request_body: bytes,
    signature_header: str,
) -> bool:
    """
    Valida la autenticidad de un webhook enviado por Meta.

    Meta envía:

        X-Hub-Signature-256: sha256=<firma>

    MAO Comunicaciones calcula:

        HMAC-SHA256(
            META_APP_SECRET,
            request.body
        )

    y compara ambas firmas de forma segura.

    Esta función:

        - no interpreta JSON;
        - no modifica datos;
        - no conoce ERP;
        - no conoce MAO Citas;
        - no conoce MAO Asistente.

    Solo valida que el webhook realmente provenga
    de Meta.
    """

    # ======================================================
    # APP SECRET
    # ======================================================

    meta_app_secret = str(
        getattr(
            settings,
            "META_APP_SECRET",
            "",
        )
        or ""
    ).strip()

    if not meta_app_secret:

        logger.error(
            "META_APP_SECRET no está configurado."
        )

        return False

    # ======================================================
    # BODY
    # ======================================================

    if not isinstance(
        request_body,
        bytes,
    ):

        logger.warning(
            "El cuerpo recibido para validar la firma "
            "no es bytes."
        )

        return False

    # ======================================================
    # HEADER
    # ======================================================

    signature_header = str(
        signature_header or ""
    ).strip()

    prefix = "sha256="

    if not signature_header.startswith(
        prefix
    ):

        logger.warning(
            "X-Hub-Signature-256 ausente o inválido."
        )

        return False

    firma_recibida = (
        signature_header[
            len(prefix):
        ]
        .strip()
        .lower()
    )

    if not firma_recibida:

        logger.warning(
            "Firma SHA256 vacía."
        )

        return False

    # SHA-256 hexadecimal debe tener 64 caracteres.
    if len(firma_recibida) != 64:

        logger.warning(
            "Firma SHA256 con longitud inválida."
        )

        return False

    # ======================================================
    # CALCULAR FIRMA
    # ======================================================

    try:

        firma_calculada = hmac.new(
            key=meta_app_secret.encode(
                "utf-8"
            ),
            msg=request_body,
            digestmod=hashlib.sha256,
        ).hexdigest()

    except Exception:

        logger.exception(
            "Error calculando la firma HMAC del webhook."
        )

        return False

    # ======================================================
    # COMPARACIÓN SEGURA
    # ======================================================

    es_valida = hmac.compare_digest(
        firma_recibida,
        firma_calculada,
    )

    if not es_valida:

        logger.warning(
            "La firma del webhook de Meta no coincide."
        )

    return es_valida