"""Verified Quo webhook parsing, replay rejection, and pipeline dispatch."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.quo.client import QUO_API_VERSION, QUO_WEBHOOK_EVENTS
from app.services.webhook_replay import (
    SignatureClaimOutcome,
    claim_webhook_signature_in_transaction,
)
from app.services.webhooks.pipeline import (
    WebhookIdempotencyDecision,
    WebhookRequestEnvelope,
)


@dataclass(frozen=True, slots=True)
class QuoWebhookEvent:
    """Minimum verified Quo envelope passed to provider-specific handlers."""

    delivery_id: str
    event_id: str
    event_type: str
    api_version: str
    organization_id: str
    created_at: str
    data: dict[str, Any]

    @property
    def provider(self) -> str:
        return "quo"

    @property
    def provider_event_id(self) -> str:
        return self.delivery_id

    @property
    def idempotency_key(self) -> str:
        return self.delivery_id

    @property
    def created_at_datetime(self) -> datetime:
        """Return the verified envelope time as timezone-aware UTC."""
        try:
            parsed = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Invalid Quo event timestamp") from None
        if parsed.tzinfo is None:
            raise ValueError("Invalid Quo event timestamp")
        return parsed.astimezone(UTC)


def parse_quo_payload(
    payload: dict[str, Any],
    request: WebhookRequestEnvelope,
    *,
    expected_organization_id: str,
    expected_api_version: str,
) -> QuoWebhookEvent:
    """Validate the signed envelope and bind it to the path's integration."""
    data = payload.get("data")
    context = data.get("context") if isinstance(data, dict) else None
    delivery_id = request.headers.get("webhook-id", "").strip()
    event_id = payload.get("id")
    event_type = payload.get("type")
    api_version = payload.get("apiVersion")
    organization_id = context.get("orgId") if isinstance(context, dict) else None
    created_at = payload.get("createdAt")

    if (
        not delivery_id
        or len(delivery_id) > 255
        or not isinstance(event_id, str)
        or not event_id
        or len(event_id) > 255
        or event_type not in QUO_WEBHOOK_EVENTS
        or api_version != expected_api_version
        or api_version != QUO_API_VERSION
        or not isinstance(organization_id, str)
        or not isinstance(created_at, str)
        or not isinstance(data, dict)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Quo webhook payload",
        )

    if not hmac.compare_digest(organization_id, expected_organization_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quo webhook organization mismatch",
        )

    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        parsed_created_at = None
    if parsed_created_at is None or parsed_created_at.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Quo webhook payload",
        )

    return QuoWebhookEvent(
        delivery_id=delivery_id,
        event_id=event_id,
        event_type=event_type,
        api_version=api_version,
        organization_id=organization_id,
        created_at=created_at,
        data=data,
    )


async def check_quo_idempotency(
    db: AsyncSession,
    event: QuoWebhookEvent,
    log: Any,
) -> WebhookIdempotencyDecision:
    """Atomically claim the signed delivery ID before any domain dispatch."""
    claim = await claim_webhook_signature_in_transaction(
        db,
        "quo",
        event.delivery_id,
        log=log,
    )
    if claim.outcome is SignatureClaimOutcome.LEDGER_UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook replay protection unavailable",
        )
    if claim.outcome is SignatureClaimOutcome.REPLAY:
        return WebhookIdempotencyDecision.duplicate("already_processed")
    return WebhookIdempotencyDecision.process()
