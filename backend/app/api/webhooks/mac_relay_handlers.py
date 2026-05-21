"""Mac relay iMessage webhook handlers."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.conversation import Conversation, Message, MessageChannel
from app.models.phone_number import PhoneNumber
from app.services.telephony.inbound_text import (
    InboundTextEvent,
    persist_inbound_text_message,
    process_inbound_text_event,
)
from app.utils.phone import normalize_phone_safe


async def handle_mac_relay_message(payload: dict[str, Any], log: Any) -> dict[str, str]:
    """Handle an inbound message event from the Mac relay."""
    if bool(payload.get("is_from_me", False)):
        log.info("mac_relay_outbound_echo_ignored", event_id=payload.get("event_id"))
        return {"status": "ignored", "reason": "outbound_echo"}

    from_number = _normalize_relay_address(_first_text(payload, "from", "sender"))
    to_number = _normalize_relay_address(
        _first_text(payload, "to", "recipient", "destination_caller_id")
    )
    body = str(payload.get("text") or payload.get("body") or "")
    relay_message_id = _first_text(payload, "message_id", "guid", "id", "event_id")
    provider_message_id = _prefix_mac_relay_id(relay_message_id) if relay_message_id else ""

    log = log.bind(
        provider_message_id=provider_message_id,
        from_number=from_number,
        to_number=to_number,
    )

    if not all([from_number, to_number, body, provider_message_id]):
        log.warning("mac_relay_missing_required_fields")
        return {"status": "ignored", "reason": "missing_required_fields"}

    async with AsyncSessionLocal() as db:
        phone_record = await _find_workspace_phone(db, to_number)
        if phone_record is None:
            log.warning("mac_relay_phone_number_not_found", to_number=to_number)
            return {"status": "ignored", "reason": "phone_number_not_found"}

        if await _message_already_ingested(db, provider_message_id, phone_record.workspace_id):
            log.info("mac_relay_duplicate_ignored", provider_message_id=provider_message_id)
            return {"status": "ok", "reason": "duplicate"}

        event = InboundTextEvent(
            provider_message_id=provider_message_id,
            from_number=from_number,
            to_number=phone_record.phone_number,
            body=body,
            workspace_id=phone_record.workspace_id,
            channel=MessageChannel.IMESSAGE,
        )

        message = await process_inbound_text_event(
            db=db,
            event=event,
            ingest_message=_build_mac_relay_ingestor(log),
            log=log,
        )
        if message is None:
            return {"status": "ok"}

        log.info("mac_relay_inbound_processed", message_id=str(message.id))
        return {"status": "ok", "message_id": str(message.id)}


def _build_mac_relay_ingestor(
    log: Any,
) -> Callable[[AsyncSession, InboundTextEvent], Awaitable[Message]]:
    """Build a relay ingestor bound to the request logger."""

    async def ingest(db: AsyncSession, event: InboundTextEvent) -> Message:
        return await persist_inbound_text_message(
            db=db,
            provider_message_id=event.provider_message_id,
            from_number=event.from_number,
            to_number=event.to_number,
            body=event.body,
            workspace_id=event.workspace_id,
            channel=MessageChannel.IMESSAGE,
            log=log,
        )

    return ingest


async def _message_already_ingested(
    db: AsyncSession,
    provider_message_id: str,
    workspace_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Message.provider_message_id == provider_message_id,
            Conversation.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def _find_workspace_phone(db: AsyncSession, to_number: str) -> PhoneNumber | None:
    """Find the workspace sender identity addressed by a relay event."""
    candidates = [to_number]
    normalized = normalize_phone_safe(to_number)
    if normalized and normalized not in candidates:
        candidates.append(normalized)

    result = await db.execute(select(PhoneNumber).where(PhoneNumber.phone_number.in_(candidates)))
    return result.scalar_one_or_none()


async def process_inbound_mac_relay_message(
    *,
    db: AsyncSession,
    provider_message_id: str,
    from_number: str,
    to_number: str,
    body: str,
    workspace_id: uuid.UUID,
    created_at: datetime | None = None,
) -> Message:
    """Provider-neutral inbound helper for tests and direct integrations."""
    event = InboundTextEvent(
        provider_message_id=_prefix_mac_relay_id(provider_message_id),
        from_number=from_number,
        to_number=to_number,
        body=body,
        workspace_id=workspace_id,
        channel=MessageChannel.IMESSAGE,
    )
    message = await persist_inbound_text_message(
        db=db,
        provider_message_id=event.provider_message_id,
        from_number=event.from_number,
        to_number=event.to_number,
        body=event.body,
        workspace_id=event.workspace_id,
        channel=MessageChannel.IMESSAGE,
        log=_NoopLog(),
    )
    if created_at is not None:
        message.created_at = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
        await db.commit()
        await db.refresh(message)
    return message


class _NoopLog:
    """Minimal logger for direct helper calls."""

    def info(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def exception(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            phone_number = value.get("phone_number")
            if isinstance(phone_number, str) and phone_number.strip():
                return phone_number.strip()
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                phone_number = first.get("phone_number")
                if isinstance(phone_number, str) and phone_number.strip():
                    return phone_number.strip()
    return ""


def _normalize_relay_address(value: str) -> str:
    if not value:
        return ""
    if "@" in value:
        return value.strip().lower()
    return normalize_phone_safe(value) or value.strip()


def _prefix_mac_relay_id(message_id: str) -> str:
    if message_id.startswith("mac-relay:"):
        return message_id
    return f"mac-relay:{message_id}"
