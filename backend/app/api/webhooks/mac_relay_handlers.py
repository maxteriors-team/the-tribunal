"""Mac relay iMessage webhook handlers.

Every database lookup here is scoped to the :class:`MacRelayCredential` the
request authenticated with (audit finding H-4). The payload's ``to``/``from``
are attacker-chosen: they may only *select within* the credential's workspace,
never widen past it.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.conversation import Conversation, Message, MessageChannel
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.services.telephony.inbound_text import (
    InboundTextEvent,
    OperatorChecker,
    check_operator_by_phone,
    persist_inbound_text_message,
    process_inbound_text_event,
)
from app.services.telephony.inbound_types import InboundMessageIngestResult
from app.services.telephony.mac_relay_auth import MacRelayCredential
from app.utils.phone import normalize_phone_safe


async def handle_mac_relay_message(
    payload: dict[str, Any],
    log: Any,
    credential: MacRelayCredential,
) -> dict[str, str]:
    """Handle an inbound message event from the Mac relay.

    ``credential`` is the tenant the request authenticated as. A credential that
    binds a workspace scopes both the sender-identity lookup and the operator
    check to it; only the legacy un-scoped token (``workspace_id is None``) falls
    back to the pre-H-4 body-derived behaviour.
    """
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
        phone_record = await _find_workspace_phone(db, to_number, credential.workspace_id)
        if phone_record is None:
            if credential.workspace_id is not None:
                # The relay authenticated as workspace X but addressed a number
                # that workspace X does not own. Pre-H-4 this silently resolved
                # to whoever *did* own it — the cross-tenant write.
                log.warning(
                    "mac_relay_cross_workspace_number_rejected",
                    security_event=True,
                    to_number=to_number,
                    workspace_id=str(credential.workspace_id),
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="phone number not found for this relay credential",
                )
            log.warning("mac_relay_phone_number_not_found", to_number=to_number)
            return {"status": "ignored", "reason": "phone_number_not_found"}

        if await _message_already_ingested(db, provider_message_id, phone_record.workspace_id):
            log.info("mac_relay_duplicate_ignored", provider_message_id=provider_message_id)
            return {"status": "ok", "reason": "duplicate"}

        sender_id = phone_record.mac_relay_sender_id
        sender_address = (
            sender_id if isinstance(sender_id, str) and sender_id else phone_record.phone_number
        )
        event = InboundTextEvent(
            provider_message_id=provider_message_id,
            from_number=from_number,
            to_number=sender_address,
            body=body,
            workspace_id=phone_record.workspace_id,
            channel=MessageChannel.IMESSAGE,
            response_channel=MessageChannel.IMESSAGE.value,
        )

        message = await process_inbound_text_event(
            db=db,
            event=event,
            ingest_message=_build_mac_relay_ingestor(log),
            log=log,
            check_operator_fn=_operator_checker_for(credential),
        )
        if message is None:
            return {"status": "ok"}

        log.info("mac_relay_inbound_processed", message_id=str(message.id))
        return {"status": "ok", "message_id": str(message.id)}


def _build_mac_relay_ingestor(
    log: Any,
) -> Callable[[AsyncSession, InboundTextEvent], Awaitable[InboundMessageIngestResult]]:
    """Build a relay ingestor bound to the request logger."""

    async def ingest(db: AsyncSession, event: InboundTextEvent) -> InboundMessageIngestResult:
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


def _operator_checker_for(credential: MacRelayCredential) -> OperatorChecker | None:
    """Return the operator lookup for this credential, pinned to its workspace.

    ``None`` (the pipeline's body-derived default) is only returned for the
    legacy un-scoped token, which carries no tenant to pin to.
    """
    if credential.workspace_id is None:
        return None
    return _build_operator_checker(credential.workspace_id)


def _build_operator_checker(pinned_workspace_id: uuid.UUID) -> OperatorChecker:
    """Pin operator identification to the authenticated workspace.

    The pipeline passes the body's ``from`` as ``from_number``, so without this
    a relay could impersonate another tenant's operator by naming a sender that
    tenant trusts. The workspace the pipeline supplies is discarded in favour of
    the credential-derived one; the parameter must still be *named*
    ``workspace_id`` because :class:`OperatorChecker` is a callable protocol and
    mypy matches parameter names — hence the distinct outer
    ``pinned_workspace_id``.
    """

    async def check_operator(
        db: AsyncSession, from_number: str, workspace_id: uuid.UUID
    ) -> User | None:
        return await check_operator_by_phone(db, from_number, pinned_workspace_id)

    return check_operator


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


async def _find_workspace_phone(
    db: AsyncSession,
    to_number: str,
    workspace_id: uuid.UUID | None,
) -> PhoneNumber | None:
    """Find the sender identity addressed by a relay event, within its tenant.

    ``workspace_id`` comes from the presented token, not the payload. Without
    that filter this query matched *any* workspace's number, so a relay host
    could name another tenant's number in ``to`` and have the message written
    into their conversations. ``None`` is only reachable via the legacy
    un-scoped global token.
    """
    candidates = [to_number]
    normalized = normalize_phone_safe(to_number)
    if normalized and normalized not in candidates:
        candidates.append(normalized)

    query = select(PhoneNumber).where(
        PhoneNumber.is_active.is_(True),
        or_(
            PhoneNumber.phone_number.in_(candidates),
            PhoneNumber.mac_relay_sender_id.in_(candidates),
        ),
    )
    if workspace_id is not None:
        query = query.where(PhoneNumber.workspace_id == workspace_id)

    result = await db.execute(query.limit(1))
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
    ingest_result = await persist_inbound_text_message(
        db=db,
        provider_message_id=event.provider_message_id,
        from_number=event.from_number,
        to_number=event.to_number,
        body=event.body,
        workspace_id=event.workspace_id,
        channel=MessageChannel.IMESSAGE,
        log=_NoopLog(),
    )
    message = ingest_result.message
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
