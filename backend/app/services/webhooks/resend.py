"""Resend webhook DTO, idempotency, and domain dispatch service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.campaign import Campaign
from app.models.conversation import (
    Conversation,
    Message,
    MessageStatus,
    advances_message_status,
)
from app.models.email_event import EmailEvent, EmailEventType
from app.services.webhooks.pipeline import (
    WebhookDispatchResult,
    WebhookIdempotencyDecision,
)

logger = structlog.get_logger()

RESEND_PROVIDER = "resend"

RESEND_EVENT_MAP: dict[str, EmailEventType] = {
    "email.sent": EmailEventType.SENT,
    "email.delivered": EmailEventType.DELIVERED,
    "email.bounced": EmailEventType.BOUNCED,
    "email.opened": EmailEventType.OPENED,
    "email.clicked": EmailEventType.CLICKED,
    "email.complained": EmailEventType.COMPLAINED,
    "email.unsubscribed": EmailEventType.UNSUBSCRIBED,
}

_CAMPAIGN_COUNTER_FIELDS: dict[EmailEventType, str] = {
    EmailEventType.SENT: "emails_sent",
    EmailEventType.DELIVERED: "emails_delivered",
    EmailEventType.BOUNCED: "emails_bounced",
    EmailEventType.OPENED: "emails_opened",
    EmailEventType.CLICKED: "emails_clicked",
    EmailEventType.UNSUBSCRIBED: "emails_unsubscribed",
}

_MESSAGE_STATUS_UPDATES: dict[EmailEventType, MessageStatus] = {
    EmailEventType.SENT: MessageStatus.SENT,
    EmailEventType.DELIVERED: MessageStatus.DELIVERED,
    EmailEventType.BOUNCED: MessageStatus.FAILED,
}


@dataclass(frozen=True, slots=True)
class ResendWebhookEvent:
    """Internal DTO for a verified Resend/Svix webhook event."""

    event_type: str
    data: dict[str, Any]
    occurred_at: datetime
    provider_event_id: str | None
    provider_message_id: str | None
    mapped_event_type: EmailEventType | None

    @property
    def provider(self) -> str:
        return RESEND_PROVIDER

    @property
    def event_id(self) -> str | None:
        return self.provider_event_id

    @property
    def idempotency_key(self) -> str | None:
        return self.provider_event_id


def parse_resend_event(
    payload: dict[str, Any],
    *,
    provider_event_id: str | None,
) -> ResendWebhookEvent:
    """Parse a verified Resend payload into the internal event DTO."""
    event_type = str(payload.get("type") or "")
    raw_data = payload.get("data")
    data = raw_data if isinstance(raw_data, dict) else {}
    raw_provider_message_id = data.get("email_id") or data.get("id")
    provider_message_id = str(raw_provider_message_id) if raw_provider_message_id else None
    return ResendWebhookEvent(
        event_type=event_type,
        data=data,
        occurred_at=_parse_occurred_at(payload.get("created_at")),
        provider_event_id=provider_event_id,
        provider_message_id=provider_message_id,
        mapped_event_type=RESEND_EVENT_MAP.get(event_type),
    )


async def check_resend_idempotency(
    db: AsyncSession,
    event: ResendWebhookEvent,
    log: Any,
) -> WebhookIdempotencyDecision:
    """Check whether a Resend event id has already been persisted."""
    if event.mapped_event_type is None:
        return WebhookIdempotencyDecision.process("unhandled_event_type")

    if event.idempotency_key is None:
        log.warning("resend_event_missing_idempotency_key", event_type=event.event_type)
        return WebhookIdempotencyDecision.process("missing_idempotency_key")

    existing = await db.execute(
        select(EmailEvent.id).where(EmailEvent.provider_event_id == event.idempotency_key)
    )
    if existing.scalar_one_or_none() is not None:
        log.info(
            "resend_event_duplicate_skipped",
            event_type=event.event_type,
            provider_event_id=event.idempotency_key,
        )
        return WebhookIdempotencyDecision.duplicate("already_processed")

    return WebhookIdempotencyDecision.process()


async def dispatch_resend_event(
    db: AsyncSession,
    event: ResendWebhookEvent,
    log: Any,
) -> WebhookDispatchResult:
    """Persist the Resend event and apply domain side effects."""
    mapped = event.mapped_event_type
    if mapped is None:
        log.debug("resend_unhandled_event", event_type=event.event_type)
        return WebhookDispatchResult.ignored("unhandled_event_type")

    message = await _find_message(db, event.provider_message_id)
    workspace_id = message.conversation.workspace_id if message else None

    if workspace_id is None:
        log.warning(
            "resend_event_no_workspace",
            event_type=event.event_type,
            provider_id=event.provider_message_id,
        )
        return WebhookDispatchResult.ignored("workspace_not_found")

    event_row = EmailEvent(
        workspace_id=workspace_id,
        message_id=message.id if message else None,
        event_type=mapped.value,
        occurred_at=event.occurred_at,
        provider_event_id=event.provider_event_id or event.provider_message_id,
        event_metadata=event.data,
    )
    db.add(event_row)

    # Resend can redeliver or reorder events for the same email; only advance
    # the stored status so a late ``email.sent`` never downgrades a message that
    # already reached DELIVERED/FAILED (bounced).
    new_status = _MESSAGE_STATUS_UPDATES.get(mapped)
    if (
        message is not None
        and new_status is not None
        and advances_message_status(message.status, new_status)
    ):
        message.status = new_status
        if mapped is EmailEventType.DELIVERED:
            message.delivered_at = event_row.occurred_at
        elif mapped is EmailEventType.SENT:
            message.sent_at = event_row.occurred_at

    counter_field = _CAMPAIGN_COUNTER_FIELDS.get(mapped)
    if counter_field is not None and message is not None and message.campaign_id is not None:
        await db.execute(
            update(Campaign)
            .where(Campaign.id == message.campaign_id)
            .values({counter_field: getattr(Campaign, counter_field) + 1})
        )

    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a concurrent retry of the same svix-id; the unique
        # constraint on provider_event_id means the other request already
        # committed this event. Roll back and treat as a successful no-op.
        await db.rollback()
        log.info(
            "resend_event_duplicate_race",
            event_type=event.event_type,
            provider_event_id=event.provider_event_id,
        )
        return WebhookDispatchResult.duplicate("already_processed")

    log.info("resend_event_processed", event_type=event.event_type, mapped=mapped.value)
    return WebhookDispatchResult.processed()


async def _find_message(db: AsyncSession, provider_message_id: str | None) -> Message | None:
    """Locate the Message (with eager-loaded conversation) for a Resend event."""
    if provider_message_id is None:
        return None

    result = await db.execute(
        select(Message)
        .options(selectinload(Message.conversation).load_only(Conversation.workspace_id))
        .where(Message.provider_message_id == provider_message_id)
    )
    return result.scalar_one_or_none()


def _parse_occurred_at(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)
