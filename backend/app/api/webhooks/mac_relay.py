"""Webhook endpoints for the self-hosted Mac iMessage relay."""

import secrets
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.webhooks.mac_relay_handlers import handle_mac_relay_message
from app.core.config import settings

router = APIRouter()
logger = structlog.get_logger()


@router.post("/messages")
async def mac_relay_messages_webhook(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, str]:
    """Handle inbound message events forwarded by the Mac relay daemon."""
    _verify_mac_relay_authorization(authorization)
    payload = await _read_json_object(request)

    log = logger.bind(endpoint="mac_relay_messages_webhook")
    log.info("mac_relay_webhook_received", event_id=payload.get("event_id"))
    try:
        return await handle_mac_relay_message(payload, log)
    except Exception as exc:
        log.exception(
            "mac_relay_handler_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Mac relay handler failed",
        ) from exc


def _verify_mac_relay_authorization(authorization: str | None) -> None:
    expected = settings.mac_relay_webhook_token or settings.mac_relay_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mac relay webhook token is not configured",
        )

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid Mac relay token",
        )


async def _read_json_object(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="JSON payload must be an object",
        )
    return payload
