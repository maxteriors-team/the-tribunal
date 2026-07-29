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


def validate_calcom_signature(
    signature: str,
    payload: bytes,
    secret: str | None = None,
) -> bool:
    """Validate Cal.com webhook signature.

    Cal.com uses HMAC-SHA256 for webhook signing.
    Header: x-cal-signature-256

    Args:
        signature: The x-cal-signature-256 header value
        payload: The raw request body
        secret: The Cal.com webhook secret (optional, uses settings if not provided)

    Returns:
        True if signature is valid, False otherwise
    """
    import hashlib
    import hmac

    if not signature:
        return False

    # Use provided secret or fall back to settings
    key = secret or settings.calcom_webhook_secret
    if not key:
        logger.warning("calcom_webhook_secret_not_configured")
        # Reject webhooks when secret is not configured
        # Use skip_webhook_verification=True for explicit dev bypass
        return False

    try:
        # Calculate expected signature
        expected_signature = hmac.new(
            key.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        # Compare signatures
        return hmac.compare_digest(signature, expected_signature)

    except Exception as e:
        logger.warning("calcom_signature_validation_failed", error=str(e))
        return False


# Best-effort freshness window for the OPTIONAL ``x-cal-timestamp`` header.
_CALCOM_TIMESTAMP_HEADER = "x-cal-timestamp"
_CALCOM_TIMESTAMP_MAX_SKEW_SECONDS = 300


def _enforce_calcom_timestamp_window(raw_timestamp: str) -> None:
    """Reject a present-but-stale/malformed ``x-cal-timestamp`` header.

    Only called when the header was actually sent. A blank or non-numeric value
    is treated as a rejection, not as "no timestamp": a caller that bothers to
    send the header does not get to neuter the check by emptying it.

    Raises:
        HTTPException: 403 if the timestamp is blank, non-numeric, or outside
            the skew window.
    """
    timestamp = raw_timestamp.strip()
    if not timestamp:
        logger.warning("calcom_webhook_blank_timestamp")
        raise HTTPException(status_code=403, detail="Invalid webhook timestamp")

    try:
        sent_at = int(timestamp)
    except ValueError as err:
        logger.warning("calcom_webhook_invalid_timestamp", timestamp=timestamp)
        raise HTTPException(status_code=403, detail="Invalid webhook timestamp") from err

    if abs(int(time.time()) - sent_at) > _CALCOM_TIMESTAMP_MAX_SKEW_SECONDS:
        logger.warning("calcom_webhook_timestamp_too_old", timestamp=timestamp)
        raise HTTPException(status_code=403, detail="Webhook timestamp too old")


async def verify_calcom_webhook(request: Request) -> bool:
    """Verify Cal.com webhook signature from request.

    Args:
        request: FastAPI request object

    Returns:
        True if signature is valid or validation is explicitly skipped

    Raises:
        HTTPException: 503 if no signing secret is configured (fail closed),
            403 if the signature is missing/invalid or a supplied timestamp is
            stale or malformed.
    """
    # Explicit opt-in to skip verification (DANGEROUS - only for local dev)
    if settings.skip_webhook_verification:
        logger.warning("webhook_verification_skipped_by_config")
        return True

    # Fail closed on a misconfigured deployment: with no secret there is no way
    # to tell a real Cal.com delivery from a forged one, so refuse to look at
    # the body at all. 503 (not 403) because the fault is ours, and it tells
    # Cal.com to retry once the secret is actually configured.
    if not settings.calcom_webhook_secret:
        logger.error("calcom_webhook_secret_not_configured")
        raise HTTPException(status_code=503, detail="Webhook secret not configured.")

    # Get signature header
    signature = request.headers.get("x-cal-signature-256", "")

    if not signature:
        logger.warning("missing_calcom_signature")
        raise HTTPException(status_code=403, detail="Missing Cal.com signature")

    # NOTE: Cal.com signs the raw body ONLY (HMAC-SHA256) and sends exactly two
    # headers — ``x-cal-signature-256`` and ``x-cal-webhook-version``. It does
    # NOT send an ``x-cal-timestamp`` header, and — this is the important part —
    # the timestamp is NOT covered by the signature. That has two consequences:
    #
    # 1. We cannot require the header: doing so 403s every real Cal.com webhook.
    # 2. Even when it is present it is unauthenticated. An attacker replaying a
    #    captured ``(body, signature)`` pair simply omits it, or forges a fresh
    #    value, and the HMAC still verifies. So this window is defence in depth
    #    against sloppy relays — it is NOT replay protection, and no amount of
    #    tightening here can make it into replay protection.
    #
    # The actual replay defence is the durable, Postgres-backed signature ledger
    # (:mod:`app.services.webhook_replay`), claimed by the router in
    # ``app/api/webhooks/calcom.py`` after this function returns and before any
    # dispatch. It does not depend on attacker-supplied input, which is exactly
    # why it — and not the timestamp — is the thing standing between us and a
    # replayed delivery. Do NOT reinstate a hard timestamp requirement here.
    #
    # What we DO tighten: if the header is sent at all it must be well formed
    # and fresh. ``headers.get(...) is not None`` distinguishes "absent" (fine)
    # from "present but blank" (rejected), so a caller cannot opt out of the
    # check while still claiming to speak the timestamped dialect.
    raw_timestamp = request.headers.get(_CALCOM_TIMESTAMP_HEADER)
    if raw_timestamp is not None:
        _enforce_calcom_timestamp_window(raw_timestamp)

    # Get raw body
    body = await request.body()

    # Validate signature — this is the actual authentication for the webhook,
    # and it runs before the caller is allowed to touch a single side effect.
    if not validate_calcom_signature(signature, body):
        logger.warning("invalid_calcom_signature")
        raise HTTPException(status_code=403, detail="Invalid Cal.com signature")

    return True
