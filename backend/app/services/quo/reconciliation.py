"""Atomic canonicalization for every Quo text-message resource."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, literal, or_, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.models.conversation import (
    Conversation,
    Message,
    MessageChannel,
    MessageDirection,
    MessageStatus,
)
from app.models.quo_send_attempt import QuoSendAttempt, QuoSendAttemptState
from app.utils.phone import normalize_phone_safe

QUO_PROVIDER = "quo"
_OUTBOUND_STATUSES = frozenset(
    {
        MessageStatus.QUEUED,
        MessageStatus.SENDING,
        MessageStatus.SENT,
        MessageStatus.FAILED,
        MessageStatus.DELIVERED,
    }
)


class QuoReconciliationError(RuntimeError):
    """A provider ID conflicted with immutable CRM message identity."""


@dataclass(frozen=True, slots=True)
class QuoMessageSnapshot:
    """Normalized provider state shared by send, webhook, and historical paths."""

    provider_message_id: str
    conversation_id: uuid.UUID
    direction: MessageDirection
    sender: str
    recipient: str
    body: str
    status: MessageStatus
    occurred_at: datetime
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    external_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    sender_user_id: int | None = None
    provider_sender_user_id: str | None = None
    sender_display_name: str | None = None


@dataclass(frozen=True, slots=True)
class QuoReconciliationResult:
    """Canonical row and whether this transaction inserted it."""

    message: Message
    created: bool


async def reconcile_quo_message(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    conversation: Conversation,
    snapshot: QuoMessageSnapshot,
    attempt: QuoSendAttempt | None = None,
) -> QuoReconciliationResult:
    """Upsert one Quo message and apply insert-only side effects atomically."""
    _validate_identity(
        workspace_id=workspace_id,
        conversation=conversation,
        snapshot=snapshot,
        attempt=attempt,
    )

    candidate_id = uuid.uuid4()
    insert_statement = pg_insert(Message).values(
        id=candidate_id,
        idempotency_key=uuid.uuid4(),
        conversation_id=conversation.id,
        channel=MessageChannel.SMS.value,
        direction=snapshot.direction.value,
        status=snapshot.status.value,
        body=snapshot.body,
        provider_message_id=snapshot.provider_message_id,
        source_provider=QUO_PROVIDER,
        external_url=snapshot.external_url,
        error_code=snapshot.error_code,
        error_message=snapshot.error_message,
        sender_user_id=snapshot.sender_user_id,
        provider_sender_user_id=snapshot.provider_sender_user_id,
        sender_display_name=snapshot.sender_display_name,
        sent_at=snapshot.sent_at,
        delivered_at=snapshot.delivered_at,
        created_at=snapshot.occurred_at,
        is_ai=False,
        is_voicemail=False,
    )
    excluded = insert_statement.excluded
    final_status = _merged_status(Message.status, excluded.status)
    statement = (
        insert_statement.on_conflict_do_update(
            index_elements=[Message.source_provider, Message.provider_message_id],
            index_where=text("source_provider = 'quo' AND provider_message_id IS NOT NULL"),
            set_={
                "body": excluded.body if snapshot.body else Message.body,
                "external_url": func.coalesce(Message.external_url, excluded.external_url),
                "sender_user_id": func.coalesce(Message.sender_user_id, excluded.sender_user_id),
                "provider_sender_user_id": func.coalesce(
                    Message.provider_sender_user_id,
                    excluded.provider_sender_user_id,
                ),
                "sender_display_name": case(
                    (
                        or_(
                            Message.sender_display_name.is_(None),
                            and_(
                                Message.provider_sender_user_id.is_not(None),
                                Message.sender_display_name == Message.provider_sender_user_id,
                            ),
                        ),
                        func.coalesce(
                            excluded.sender_display_name,
                            Message.sender_display_name,
                        ),
                    ),
                    else_=Message.sender_display_name,
                ),
                "status": final_status,
                "sent_at": _greatest_nullable(Message.sent_at, excluded.sent_at),
                "delivered_at": _greatest_nullable(
                    Message.delivered_at,
                    excluded.delivered_at,
                ),
                "created_at": func.least(Message.created_at, excluded.created_at),
                "error_code": case(
                    (final_status == MessageStatus.DELIVERED.value, None),
                    (
                        final_status == MessageStatus.FAILED.value,
                        func.coalesce(excluded.error_code, Message.error_code),
                    ),
                    else_=Message.error_code,
                ),
                "error_message": case(
                    (final_status == MessageStatus.DELIVERED.value, None),
                    (
                        final_status == MessageStatus.FAILED.value,
                        func.coalesce(excluded.error_message, Message.error_message),
                    ),
                    else_=Message.error_message,
                ),
            },
            where=and_(
                Message.source_provider == QUO_PROVIDER,
                Message.conversation_id == conversation.id,
                Message.direction == snapshot.direction.value,
                Message.channel == MessageChannel.SMS.value,
            ),
        )
        .returning(Message)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(statement)
    message = result.scalar_one_or_none()
    if message is None:
        raise QuoReconciliationError(
            "Quo provider message ID conflicts with immutable message identity"
        )

    created = message.id == candidate_id
    await _update_conversation_activity(
        db,
        workspace_id=workspace_id,
        conversation=conversation,
        snapshot=snapshot,
        created=created,
    )
    if attempt is not None:
        attempt.state = QuoSendAttemptState.ACCEPTED
        attempt.provider_message_id = snapshot.provider_message_id
        attempt.message_id = message.id
        attempt.error_class = None
        await db.flush()
    return QuoReconciliationResult(message=message, created=created)


def _validate_identity(
    *,
    workspace_id: uuid.UUID,
    conversation: Conversation,
    snapshot: QuoMessageSnapshot,
    attempt: QuoSendAttempt | None,
) -> None:
    sender = normalize_phone_safe(snapshot.sender)
    recipient = normalize_phone_safe(snapshot.recipient)
    if (
        conversation.id != snapshot.conversation_id
        or conversation.workspace_id != workspace_id
        or sender is None
        or recipient is None
        or len(snapshot.provider_message_id) > 255
        or not snapshot.provider_message_id.strip()
        or (
            snapshot.provider_sender_user_id is not None
            and len(snapshot.provider_sender_user_id) > 255
        )
        or (snapshot.sender_display_name is not None and len(snapshot.sender_display_name) > 255)
        or snapshot.occurred_at.tzinfo is None
    ):
        raise QuoReconciliationError("Quo message identity is invalid")

    expected_sender = (
        conversation.contact_phone
        if snapshot.direction == MessageDirection.INBOUND
        else conversation.workspace_phone
    )
    expected_recipient = (
        conversation.workspace_phone
        if snapshot.direction == MessageDirection.INBOUND
        else conversation.contact_phone
    )
    if sender != expected_sender or recipient != expected_recipient:
        raise QuoReconciliationError("Quo message participants changed")
    if snapshot.direction == MessageDirection.INBOUND:
        if snapshot.status != MessageStatus.RECEIVED:
            raise QuoReconciliationError("Inbound Quo message status is invalid")
    elif snapshot.status not in _OUTBOUND_STATUSES:
        raise QuoReconciliationError("Outbound Quo message status is invalid")

    for timestamp in (snapshot.sent_at, snapshot.delivered_at):
        if timestamp is not None and timestamp.tzinfo is None:
            raise QuoReconciliationError("Quo lifecycle timestamp is invalid")
    if attempt is not None and (
        attempt.workspace_id != workspace_id
        or attempt.conversation_id != conversation.id
        or attempt.state != QuoSendAttemptState.SENDING
    ):
        raise QuoReconciliationError("Quo send attempt identity is invalid")


async def _update_conversation_activity(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    conversation: Conversation,
    snapshot: QuoMessageSnapshot,
    created: bool,
) -> None:
    newer = or_(
        Conversation.last_message_at.is_(None),
        Conversation.last_message_at < snapshot.occurred_at,
    )
    statement = (
        update(Conversation)
        .where(
            Conversation.id == conversation.id,
            Conversation.workspace_id == workspace_id,
        )
        .values(
            source_provider=QUO_PROVIDER,
            last_message_at=case(
                (newer, snapshot.occurred_at),
                else_=Conversation.last_message_at,
            ),
            last_message_preview=case(
                (newer, snapshot.body[:500]),
                else_=Conversation.last_message_preview,
            ),
            last_message_direction=case(
                (newer, snapshot.direction.value),
                else_=Conversation.last_message_direction,
            ),
            channel=case(
                (newer, MessageChannel.SMS.value),
                else_=Conversation.channel,
            ),
            unread_count=Conversation.unread_count
            + int(created and snapshot.direction == MessageDirection.INBOUND),
        )
        .returning(Conversation.id)
    )
    updated_id = (await db.execute(statement)).scalar_one_or_none()
    if updated_id is None:
        raise QuoReconciliationError("Quo conversation is outside the workspace")


def _merged_status(
    existing: ColumnElement[Any] | InstrumentedAttribute[Any],
    candidate: ColumnElement[Any] | InstrumentedAttribute[Any],
) -> ColumnElement[Any]:
    return case(
        (
            or_(
                existing == MessageStatus.DELIVERED.value,
                candidate == MessageStatus.DELIVERED.value,
            ),
            literal(MessageStatus.DELIVERED.value),
        ),
        (
            or_(
                existing == MessageStatus.FAILED.value,
                candidate == MessageStatus.FAILED.value,
            ),
            literal(MessageStatus.FAILED.value),
        ),
        (
            or_(
                existing == MessageStatus.SENT.value,
                candidate == MessageStatus.SENT.value,
            ),
            literal(MessageStatus.SENT.value),
        ),
        (
            or_(
                existing == MessageStatus.SENDING.value,
                candidate == MessageStatus.SENDING.value,
            ),
            literal(MessageStatus.SENDING.value),
        ),
        (
            or_(
                existing == MessageStatus.RECEIVED.value,
                candidate == MessageStatus.RECEIVED.value,
            ),
            literal(MessageStatus.RECEIVED.value),
        ),
        else_=literal(MessageStatus.QUEUED.value),
    )


def _greatest_nullable(
    existing: ColumnElement[Any] | InstrumentedAttribute[Any],
    candidate: ColumnElement[Any] | InstrumentedAttribute[Any],
) -> ColumnElement[Any]:
    return case(
        (existing.is_(None), candidate),
        (candidate.is_(None), existing),
        else_=func.greatest(existing, candidate),
    )
