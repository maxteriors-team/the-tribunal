"""Webhook signature validation for Telnyx."""

import base64
import time
from functools import wraps
from typing import Any

import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException, Request

from app.core.config import settings

logger = structlog.get_logger()


def validate_telnyx_signature(
    signature: str,
    timestamp: str,
    payload: bytes,
    public_key: str | None = None,
) -> bool:
    """Validate Telnyx webhook signature.

    Telnyx uses ed25519 signatures for webhook validation.
    Headers: telnyx-signature-ed25519, telnyx-timestamp

    Args:
        signature: The telnyx-signature-ed25519 header value
        timestamp: The telnyx-timestamp header value
        payload: The raw request body
        public_key: The Telnyx public key (optional, uses settings if not provided)

    Returns:
        True if signature is valid, False otherwise
    """
    if not signature or not timestamp:
        return False

    # Use provided key or fall back to settings
    key = public_key or settings.telnyx_public_key
    if not key:
        logger.warning("telnyx_public_key_not_configured")
        # Reject webhooks when public key is not configured
        # Use skip_webhook_verification=True for explicit dev bypass
        return False

    try:
        # Decode the public key
        public_key_bytes = base64.b64decode(key)
        ed25519_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)

        # Create the signed payload (timestamp + payload)
        signed_payload = f"{timestamp}|".encode() + payload

        # Decode and verify signature
        signature_bytes = base64.b64decode(signature)
        ed25519_key.verify(signature_bytes, signed_payload)

        return True
    except Exception as e:
        logger.warning("telnyx_signature_validation_failed", error=str(e))
        return False


async def verify_telnyx_webhook(request: Request) -> bool:
    """Verify Telnyx webhook signature from request.

    Args:
        request: FastAPI request object

    Returns:
        True if signature is valid or validation is explicitly skipped

    Raises:
        HTTPException: If signature validation fails
    """
    # Explicit opt-in to skip verification (DANGEROUS - only for local dev)
    if settings.skip_webhook_verification:
        logger.warning("webhook_verification_skipped_by_config")
        return True

    # Get signature headers
    signature = request.headers.get("telnyx-signature-ed25519", "")
    timestamp = request.headers.get("telnyx-timestamp", "")

    if not signature or not timestamp:
        logger.warning("missing_telnyx_signature")
        raise HTTPException(status_code=403, detail="Missing Telnyx signature")

    # Reject requests with timestamps older than 5 minutes (replay-attack prevention)
    try:
        current_time = int(time.time())
        if abs(current_time - int(timestamp)) > 300:
            logger.warning("telnyx_webhook_timestamp_too_old", timestamp=timestamp)
            raise HTTPException(status_code=403, detail="Webhook timestamp too old")
    except ValueError as err:
        logger.warning("telnyx_webhook_invalid_timestamp", timestamp=timestamp)
        raise HTTPException(status_code=403, detail="Invalid webhook timestamp") from err

    # Get raw body
    body = await request.body()

    # Validate signature
    if not validate_telnyx_signature(signature, timestamp, body):
        logger.warning("invalid_telnyx_signature")
        raise HTTPException(status_code=403, detail="Invalid Telnyx signature")

    return True


def require_telnyx_signature(func: Any) -> Any:
    """Decorator to require valid Telnyx signature on webhook endpoints."""

    @wraps(func)
    async def wrapper(request: Request, *args: Any, **kwargs: Any) -> Any:
        await verify_telnyx_webhook(request)
        return await func(request, *args, **kwargs)

    return wrapper
