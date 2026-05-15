"""Handlers for Resend webhook events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.campaign import Campaign
from app.models.conversation import Conversation, Message, MessageStatus
from app.models.email_event import EmailEvent, EmailEventType

logger = structlog.get_logger()


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


def _parse_occurred_at(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


async def _find_message(
    db: AsyncSession, data: dict[str, Any]
) -> Message | None:
    """Locate the Message (with eager-loaded conversation) for a Resend event."""
    provider_id = data.get("email_id") or data.get("id")
    if not provider_id:
        return None

    result = await db.execute(
        select(Message)
        .options(selectinload(Message.conversation).load_only(Conversation.workspace_id))
        .where(Message.provider_message_id == str(provider_id))
    )
    return result.scalar_one_or_none()


async def handle_event(
    db: AsyncSession,
    event: dict[str, Any],
    log: Any = None,
    provider_event_id: str | None = None,
) -> None:
    """Process a verified Resend webhook event.

    ``provider_event_id`` should be the ``svix-id`` header value, which Svix
    guarantees is stable across retries of the same event. It is used as the
    idempotency key so retried deliveries do not create duplicate
    ``EmailEvent`` rows nor double-increment campaign counters.
    """
    log = log or logger
    event_type = event.get("type", "")
    data = event.get("data") or {}

    mapped = RESEND_EVENT_MAP.get(event_type)
    if mapped is None:
        log.debug("resend_unhandled_event", event_type=event_type)
        return

    # Idempotency: if we've already processed this svix-id, skip it.
    if provider_event_id:
        existing = await db.execute(
            select(EmailEvent.id).where(
                EmailEvent.provider_event_id == provider_event_id
            )
        )
        if existing.scalar_one_or_none() is not None:
            log.info(
                "resend_event_duplicate_skipped",
                event_type=event_type,
                provider_event_id=provider_event_id,
            )
            return

    message = await _find_message(db, data)
    workspace_id = message.conversation.workspace_id if message else None

    if workspace_id is None:
        log.warning(
            "resend_event_no_workspace",
            event_type=event_type,
            provider_id=data.get("email_id"),
        )
        return

    event_row = EmailEvent(
        workspace_id=workspace_id,
        message_id=message.id if message else None,
        event_type=mapped.value,
        occurred_at=_parse_occurred_at(event.get("created_at")),
        provider_event_id=provider_event_id
        or str(data.get("email_id") or data.get("id") or "")
        or None,
        event_metadata=data,
    )
    db.add(event_row)

    new_status = _MESSAGE_STATUS_UPDATES.get(mapped)
    if message is not None and new_status is not None:
        message.status = new_status
        if mapped is EmailEventType.DELIVERED:
            message.delivered_at = event_row.occurred_at
        elif mapped is EmailEventType.SENT:
            message.sent_at = event_row.occurred_at

    counter_field = _CAMPAIGN_COUNTER_FIELDS.get(mapped)
    if (
        counter_field is not None
        and message is not None
        and message.campaign_id is not None
    ):
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
            event_type=event_type,
            provider_event_id=provider_event_id,
        )
        return
    log.info("resend_event_processed", event_type=event_type, mapped=mapped.value)
