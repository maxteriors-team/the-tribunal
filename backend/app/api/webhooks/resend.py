"""Resend webhook endpoint."""

import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import DB
from app.api.webhooks.resend_handlers import handle_event
from app.core.config import settings

try:
    from svix.webhooks import Webhook, WebhookVerificationError

    SVIX_AVAILABLE = True
except ImportError:
    SVIX_AVAILABLE = False

router = APIRouter()
logger = structlog.get_logger()


def _verify_signature(payload: bytes, headers: dict[str, str]) -> dict[str, Any]:
    """Verify the Svix signature on a Resend webhook and return the parsed event."""
    secret = settings.resend_webhook_secret

    if not secret:
        logger.warning("resend_webhook_secret_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured.",
        )

    if not SVIX_AVAILABLE:
        logger.error("svix_not_installed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="svix package not installed",
        )

    try:
        wh = Webhook(secret)
        verified = wh.verify(payload, headers)
    except WebhookVerificationError as exc:
        logger.warning("resend_webhook_verification_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        ) from exc

    if isinstance(verified, dict):
        return verified
    parsed: dict[str, Any] = json.loads(payload)
    return parsed


@router.post("")
async def resend_webhook(request: Request, db: DB) -> dict[str, str]:
    """Handle incoming Resend webhook events (email.sent, email.delivered, etc.)."""
    log = logger.bind(endpoint="resend_webhook")
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    event = _verify_signature(body, headers)
    # svix-id is unique per webhook event and stable across retries — use it
    # as the idempotency key when persisting the event.
    svix_id = headers.get("svix-id") or headers.get("webhook-id")
    log = log.bind(event_type=event.get("type"), svix_id=svix_id)
    log.info("resend_webhook_received")

    await handle_event(db, event, log, provider_event_id=svix_id)
    return {"status": "ok"}
