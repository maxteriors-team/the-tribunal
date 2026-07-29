"""Webhook endpoints for the self-hosted Mac iMessage relay.

Authentication is per-workspace (audit finding H-4): the bearer token a relay
host presents resolves to exactly one ``phone_numbers`` row, and that row's
``workspace_id`` — never the request body — decides the tenant. See
:mod:`app.services.telephony.mac_relay_auth`.
"""

import secrets
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.webhooks.mac_relay_handlers import handle_mac_relay_message
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.telephony.mac_relay_auth import (
    MacRelayCredential,
    mac_relay_credentials_configured,
    resolve_mac_relay_credential,
)

router = APIRouter()
logger = structlog.get_logger()


@router.post("/messages")
async def mac_relay_messages_webhook(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, str]:
    """Handle inbound message events forwarded by the Mac relay daemon."""
    log = logger.bind(endpoint="mac_relay_messages_webhook")
    credential = await _authenticate_mac_relay(authorization, log)
    payload = await _read_json_object(request)

    log = log.bind(**credential.log_context)
    log.info("mac_relay_webhook_received", event_id=payload.get("event_id"))
    try:
        return await handle_mac_relay_message(payload, log, credential)
    except HTTPException:
        # Tenancy rejections (404) and other deliberate status codes raised by
        # the handler are the answer — do not launder them into a 500.
        raise
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


async def _authenticate_mac_relay(authorization: str | None, log: Any) -> MacRelayCredential:
    """Resolve the presented bearer token to the workspace it is bound to.

    The token *is* the tenancy decision, so an unresolvable one can never fall
    through to a body-derived workspace. 503 is reserved for "this deployment
    has no relay credentials at all", preserving the endpoint's fail-closed
    posture; anything else is a 401.
    """
    token = _bearer_token(authorization)

    async with AsyncSessionLocal() as db:
        credential = await resolve_mac_relay_credential(db, token)
        if credential is not None:
            return credential

        legacy = _legacy_global_credential(token, log)
        if legacy is not None:
            return legacy

        provisioned = await mac_relay_credentials_configured(db)

    if not provisioned:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mac relay webhook token is not configured",
        )

    log.warning("mac_relay_token_rejected", security_event=True)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid Mac relay token",
    )


def _legacy_global_credential(token: str, log: Any) -> MacRelayCredential | None:
    """Accept the pre-H-4 shared token, only while the escape hatch is on.

    Returns an un-scoped credential (``workspace_id is None``), which downstream
    reads as "no tenant binding" and handles with the old body-derived path.
    """
    if not settings.mac_relay_allow_legacy_global_token:
        return None

    expected = settings.mac_relay_webhook_token or settings.mac_relay_token
    if not expected or not token or not secrets.compare_digest(token, expected):
        return None

    log.warning(
        "mac_relay_legacy_global_token_used",
        security_event=True,
        detail="relay authenticated with the un-scoped global token; issue a per-workspace token",
    )
    return MacRelayCredential(workspace_id=None)


def _bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


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
