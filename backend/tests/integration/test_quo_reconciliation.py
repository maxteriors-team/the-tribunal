"""PostgreSQL concurrency proofs for canonical Quo text messages."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.contact import Contact
from app.models.conversation import (
    Conversation,
    Message,
    MessageChannel,
    MessageDirection,
    MessageStatus,
)
from app.models.quo_send_attempt import QuoSendAttempt, QuoSendAttemptState
from app.models.workspace import Workspace
from app.services.quo.outbound import (
    QuoOutboundSender,
    QuoSendStatusUnknownError,
    claim_quo_send_attempt,
    execute_quo_send,
)
from app.services.quo.reconciliation import (
    QuoMessageSnapshot,
    QuoReconciliationError,
    reconcile_quo_message,
)

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.integration]

WORKSPACE_PHONE = "+14155552671"
CONTACT_PHONE = "+14155552672"


@asynccontextmanager
async def _db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


async def _thread(label: str) -> tuple[uuid.UUID, uuid.UUID]:
    async with _db_session() as db:
        workspace = Workspace(name=label, slug=f"quo-reconcile-{uuid.uuid4().hex}")
        db.add(workspace)
        await db.flush()
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Quo",
            last_name="Race",
            phone_number=CONTACT_PHONE,
        )
        db.add(contact)
        await db.flush()
        conversation = Conversation(
            workspace_id=workspace.id,
            contact_id=contact.id,
            channel=MessageChannel.SMS,
            contact_phone=CONTACT_PHONE,
            workspace_phone=WORKSPACE_PHONE,
            source_provider="quo",
            ai_enabled=False,
        )
        db.add(conversation)
        await db.commit()
        return workspace.id, conversation.id


async def _cleanup(workspace_id: uuid.UUID) -> None:
    async with _db_session() as db:
        workspace = await db.get(Workspace, workspace_id)
        if workspace is not None:
            await db.delete(workspace)
            await db.commit()


def _snapshot(
    *,
    provider_message_id: str,
    conversation_id: uuid.UUID,
    status: MessageStatus,
    occurred_at: datetime,
    body: str = "One canonical message",
) -> QuoMessageSnapshot:
    return QuoMessageSnapshot(
        provider_message_id=provider_message_id,
        conversation_id=conversation_id,
        direction=MessageDirection.OUTBOUND,
        sender=WORKSPACE_PHONE,
        recipient=CONTACT_PHONE,
        body=body,
        status=status,
        occurred_at=occurred_at,
        sent_at=occurred_at if status != MessageStatus.QUEUED else None,
        delivered_at=occurred_at if status == MessageStatus.DELIVERED else None,
    )


async def test_three_writers_reconcile_one_row_and_one_accepted_attempt() -> None:
    workspace_id, conversation_id = await _thread("Quo three-writer race")
    provider_message_id = f"AC_race_{uuid.uuid4().hex}"
    request_id = uuid.uuid4()
    base_time = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    async with _db_session() as db:
        attempt = QuoSendAttempt(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            client_request_id=request_id,
            state=QuoSendAttemptState.SENDING,
        )
        db.add(attempt)
        await db.commit()
        attempt_id = attempt.id

    barrier = asyncio.Barrier(3)

    async def write(
        status: MessageStatus,
        occurred_at: datetime,
        *,
        link_attempt: bool = False,
    ) -> tuple[uuid.UUID, bool]:
        async with _db_session() as db:
            conversation = await db.get(Conversation, conversation_id)
            assert conversation is not None
            attempt = await db.get(QuoSendAttempt, attempt_id) if link_attempt else None
            await barrier.wait()
            result = await reconcile_quo_message(
                db,
                workspace_id=workspace_id,
                conversation=conversation,
                snapshot=_snapshot(
                    provider_message_id=provider_message_id,
                    conversation_id=conversation_id,
                    status=status,
                    occurred_at=occurred_at,
                ),
                attempt=attempt,
            )
            await db.commit()
            return result.message.id, result.created

    try:
        results = await asyncio.gather(
            write(MessageStatus.QUEUED, base_time, link_attempt=True),
            write(MessageStatus.DELIVERED, base_time + timedelta(minutes=2)),
            write(MessageStatus.SENT, base_time - timedelta(minutes=2)),
        )

        async with _db_session() as db:
            messages = list(
                await db.scalars(
                    select(Message).where(
                        Message.source_provider == "quo",
                        Message.provider_message_id == provider_message_id,
                    )
                )
            )
            attempt = await db.get(QuoSendAttempt, attempt_id)
            conversation = await db.get(Conversation, conversation_id)

            assert len(messages) == 1
            assert len({message_id for message_id, _created in results}) == 1
            assert sum(created for _message_id, created in results) == 1
            assert messages[0].status == MessageStatus.DELIVERED
            assert messages[0].delivered_at == base_time + timedelta(minutes=2)
            assert attempt is not None
            assert attempt.state == QuoSendAttemptState.ACCEPTED
            assert attempt.message_id == messages[0].id
            assert conversation is not None
            assert conversation.last_message_at == base_time + timedelta(minutes=2)
            assert conversation.unread_count == 0
    finally:
        await _cleanup(workspace_id)


async def test_webhook_before_provider_response_links_existing_canonical_row() -> None:
    workspace_id, conversation_id = await _thread("Quo reverse-order race")
    provider_message_id = f"AC_reverse_{uuid.uuid4().hex}"
    occurred_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    try:
        async with _db_session() as db:
            conversation = await db.get(Conversation, conversation_id)
            assert conversation is not None
            first = await reconcile_quo_message(
                db,
                workspace_id=workspace_id,
                conversation=conversation,
                snapshot=_snapshot(
                    provider_message_id=provider_message_id,
                    conversation_id=conversation_id,
                    status=MessageStatus.DELIVERED,
                    occurred_at=occurred_at,
                ),
            )
            await db.commit()
            canonical_id = first.message.id

        async with _db_session() as db:
            conversation = await db.get(Conversation, conversation_id)
            assert conversation is not None
            attempt = QuoSendAttempt(
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                client_request_id=uuid.uuid4(),
                state=QuoSendAttemptState.SENDING,
            )
            db.add(attempt)
            await db.commit()
            result = await reconcile_quo_message(
                db,
                workspace_id=workspace_id,
                conversation=conversation,
                snapshot=_snapshot(
                    provider_message_id=provider_message_id,
                    conversation_id=conversation_id,
                    status=MessageStatus.QUEUED,
                    occurred_at=occurred_at - timedelta(seconds=5),
                ),
                attempt=attempt,
            )
            await db.commit()

            assert result.created is False
            assert result.message.id == canonical_id
            assert result.message.status == MessageStatus.DELIVERED
            assert attempt.state == QuoSendAttemptState.ACCEPTED
            assert attempt.message_id == canonical_id
    finally:
        await _cleanup(workspace_id)


async def test_sparse_snapshot_can_be_enriched_without_erasing_richer_body() -> None:
    workspace_id, conversation_id = await _thread("Quo sparse reconciliation")
    provider_message_id = f"AC_sparse_{uuid.uuid4().hex}"
    occurred_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    try:
        async with _db_session() as db:
            conversation = await db.get(Conversation, conversation_id)
            assert conversation is not None
            await reconcile_quo_message(
                db,
                workspace_id=workspace_id,
                conversation=conversation,
                snapshot=_snapshot(
                    provider_message_id=provider_message_id,
                    conversation_id=conversation_id,
                    status=MessageStatus.QUEUED,
                    occurred_at=occurred_at,
                    body="",
                ),
            )
            await db.commit()

        async with _db_session() as db:
            conversation = await db.get(Conversation, conversation_id)
            assert conversation is not None
            result = await reconcile_quo_message(
                db,
                workspace_id=workspace_id,
                conversation=conversation,
                snapshot=_snapshot(
                    provider_message_id=provider_message_id,
                    conversation_id=conversation_id,
                    status=MessageStatus.DELIVERED,
                    occurred_at=occurred_at + timedelta(minutes=1),
                    body="Full webhook body",
                ),
            )
            await db.commit()
            assert result.message.body == "Full webhook body"

        async with _db_session() as db:
            conversation = await db.get(Conversation, conversation_id)
            assert conversation is not None
            result = await reconcile_quo_message(
                db,
                workspace_id=workspace_id,
                conversation=conversation,
                snapshot=_snapshot(
                    provider_message_id=provider_message_id,
                    conversation_id=conversation_id,
                    status=MessageStatus.QUEUED,
                    occurred_at=occurred_at,
                    body="",
                ),
            )
            await db.commit()
            assert result.message.body == "Full webhook body"
            assert result.message.status == MessageStatus.DELIVERED
    finally:
        await _cleanup(workspace_id)


async def test_provider_id_cannot_cross_workspace_identity() -> None:
    workspace_a, conversation_a = await _thread("Quo tenant A")
    workspace_b, conversation_b = await _thread("Quo tenant B")
    provider_message_id = f"AC_tenant_{uuid.uuid4().hex}"
    occurred_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    try:
        async with _db_session() as db:
            conversation = await db.get(Conversation, conversation_a)
            assert conversation is not None
            await reconcile_quo_message(
                db,
                workspace_id=workspace_a,
                conversation=conversation,
                snapshot=_snapshot(
                    provider_message_id=provider_message_id,
                    conversation_id=conversation_a,
                    status=MessageStatus.SENT,
                    occurred_at=occurred_at,
                ),
            )
            await db.commit()

        async with _db_session() as db:
            conversation = await db.get(Conversation, conversation_b)
            assert conversation is not None
            with pytest.raises(QuoReconciliationError, match="immutable"):
                await reconcile_quo_message(
                    db,
                    workspace_id=workspace_b,
                    conversation=conversation,
                    snapshot=_snapshot(
                        provider_message_id=provider_message_id,
                        conversation_id=conversation_b,
                        status=MessageStatus.DELIVERED,
                        occurred_at=occurred_at + timedelta(minutes=1),
                    ),
                )
            await db.rollback()

        async with _db_session() as db:
            message = await db.scalar(
                select(Message).where(Message.provider_message_id == provider_message_id)
            )
            assert message is not None
            assert message.conversation_id == conversation_a
            assert message.status == MessageStatus.SENT
    finally:
        await _cleanup(workspace_a)
        await _cleanup(workspace_b)


async def test_provider_id_cannot_change_participants_within_conversation() -> None:
    workspace_id, conversation_id = await _thread("Quo participant identity")
    try:
        async with _db_session() as db:
            conversation = await db.get(Conversation, conversation_id)
            assert conversation is not None
            snapshot = replace(
                _snapshot(
                    provider_message_id=f"AC_participant_{uuid.uuid4().hex}",
                    conversation_id=conversation_id,
                    status=MessageStatus.SENT,
                    occurred_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
                ),
                recipient="+14155559999",
            )

            with pytest.raises(QuoReconciliationError, match="participants changed"):
                await reconcile_quo_message(
                    db,
                    workspace_id=workspace_id,
                    conversation=conversation,
                    snapshot=snapshot,
                )
    finally:
        await _cleanup(workspace_id)


async def test_ambiguous_transport_creates_unknown_attempt_then_one_webhook_message() -> None:
    workspace_id, conversation_id = await _thread("Quo ambiguous transport")
    request_id = uuid.uuid4()
    provider_message_id = f"AC_later_{uuid.uuid4().hex}"
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        raise httpx.ConnectError("connection dropped", request=request)

    try:
        async with _db_session() as db:
            claim = await claim_quo_send_attempt(
                db,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                client_request_id=request_id,
            )
            sender = QuoOutboundSender("quo_test_key", transport=httpx.MockTransport(handler))
            try:
                with pytest.raises(QuoSendStatusUnknownError):
                    await execute_quo_send(
                        db,
                        attempt=claim.attempt,
                        sender=sender,
                        content="Possibly accepted",
                        from_number=WORKSPACE_PHONE,
                        to_number=CONTACT_PHONE,
                    )
            finally:
                await sender.close()

        async with _db_session() as db:
            assert (
                await db.scalar(
                    select(func.count(Message.id))
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(Conversation.workspace_id == workspace_id)
                )
                == 0
            )
            attempt = await db.scalar(
                select(QuoSendAttempt).where(
                    QuoSendAttempt.workspace_id == workspace_id,
                    QuoSendAttempt.client_request_id == request_id,
                )
            )
            assert attempt is not None
            assert attempt.state == QuoSendAttemptState.UNKNOWN
            with pytest.raises(QuoSendStatusUnknownError):
                await claim_quo_send_attempt(
                    db,
                    workspace_id=workspace_id,
                    conversation_id=conversation_id,
                    client_request_id=request_id,
                )

        async with _db_session() as db:
            conversation = await db.get(Conversation, conversation_id)
            assert conversation is not None
            result = await reconcile_quo_message(
                db,
                workspace_id=workspace_id,
                conversation=conversation,
                snapshot=_snapshot(
                    provider_message_id=provider_message_id,
                    conversation_id=conversation_id,
                    status=MessageStatus.DELIVERED,
                    occurred_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
                ),
            )
            await db.commit()
            assert result.created is True

        async with _db_session() as db:
            assert (
                await db.scalar(
                    select(func.count(Message.id)).where(
                        Message.source_provider == "quo",
                        Message.provider_message_id == provider_message_id,
                    )
                )
                == 1
            )
        assert requests == 1
    finally:
        await _cleanup(workspace_id)
