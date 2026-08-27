"""Workspace, sender-line, and consent boundaries for Quo manual replies."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1.contacts import get_contact_timeline
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
from app.models.workspace import Workspace, WorkspaceIntegration
from app.services.conversations.conversation_service import ConversationService
from app.services.quo.outbound import QuoSendStatusUnknownError

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


async def _records(
    label: str,
    *,
    consent_status: str = "unknown",
    selected_phone: str = WORKSPACE_PHONE,
) -> tuple[Workspace, Contact, Conversation]:
    async with _db_session() as db:
        workspace = Workspace(name=label, slug=f"quo-send-{uuid.uuid4().hex}")
        db.add(workspace)
        await db.flush()
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Quo",
            last_name="Contact",
            phone_number=CONTACT_PHONE,
            sms_consent_status=consent_status,
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
        integration = WorkspaceIntegration(
            workspace_id=workspace.id,
            integration_type="quo",
            encrypted_credentials="temporary",
            is_active=True,
        )
        integration.credentials = {
            "api_key": "quo_test_key",
            "phone_number_id": "PN_selected",
            "phone_number": selected_phone,
        }
        db.add_all([conversation, integration])
        await db.commit()
        return workspace, contact, conversation


async def _cleanup(workspace_id: uuid.UUID) -> None:
    async with _db_session() as db:
        workspace = await db.get(Workspace, workspace_id)
        if workspace is not None:
            await db.delete(workspace)
            await db.commit()


async def test_unknown_consent_without_inbound_blocks_before_attempt_or_network() -> None:
    workspace, _contact, conversation = await _records("Quo unknown consent")
    try:
        async with _db_session() as db:
            persisted = await db.get(Conversation, conversation.id)
            assert persisted is not None
            with (
                patch(
                    "app.services.conversations.conversation_service.claim_quo_send_attempt",
                    new=AsyncMock(),
                ) as claim_mock,
                pytest.raises(HTTPException) as exc_info,
            ):
                await ConversationService(db)._send_quo_message(
                    conversation=persisted,
                    workspace_id=workspace.id,
                    body="Starting outbound",
                    sender_user_id=1,
                    sender_display_name="Operator",
                    client_request_id=uuid.uuid4(),
                )

            assert exc_info.value.status_code == 403
            claim_mock.assert_not_awaited()
            assert (
                await db.scalar(
                    select(func.count(QuoSendAttempt.id)).where(
                        QuoSendAttempt.workspace_id == workspace.id
                    )
                )
                == 0
            )
    finally:
        await _cleanup(workspace.id)


@pytest.mark.parametrize("consent_status", ["unknown", "opted_in"])
async def test_inbound_history_or_explicit_opt_in_reaches_the_send_claim(
    consent_status: str,
) -> None:
    workspace, _contact, conversation = await _records(
        f"Quo allowed {consent_status}",
        consent_status=consent_status,
    )
    try:
        async with _db_session() as db:
            persisted = await db.get(Conversation, conversation.id)
            assert persisted is not None
            if consent_status == "unknown":
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        channel=MessageChannel.SMS,
                        direction=MessageDirection.INBOUND,
                        status=MessageStatus.RECEIVED,
                        body="Customer started this thread",
                        source_provider="quo",
                    )
                )
                await db.commit()

            request_id = uuid.uuid4()
            with (
                patch(
                    "app.services.conversations.conversation_service.claim_quo_send_attempt",
                    new=AsyncMock(
                        side_effect=QuoSendStatusUnknownError("stop before provider network")
                    ),
                ) as claim_mock,
                pytest.raises(HTTPException) as exc_info,
            ):
                await ConversationService(db)._send_quo_message(
                    conversation=persisted,
                    workspace_id=workspace.id,
                    body="Direct reply",
                    sender_user_id=1,
                    sender_display_name="Operator",
                    client_request_id=request_id,
                )

            assert exc_info.value.status_code == 409
            claim_mock.assert_awaited_once_with(
                db,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                client_request_id=request_id,
            )
    finally:
        await _cleanup(workspace.id)


async def test_accepted_replay_returns_canonical_message_after_later_opt_out() -> None:
    workspace, contact, conversation = await _records(
        "Quo accepted replay",
        consent_status="opted_in",
    )
    request_id = uuid.uuid4()
    try:
        async with _db_session() as db:
            message = Message(
                conversation_id=conversation.id,
                channel=MessageChannel.SMS,
                direction=MessageDirection.OUTBOUND,
                status=MessageStatus.SENT,
                body="Already accepted",
                source_provider="quo",
                provider_message_id=f"AC_replay_{uuid.uuid4().hex}",
            )
            db.add(message)
            await db.flush()
            db.add(
                QuoSendAttempt(
                    workspace_id=workspace.id,
                    conversation_id=conversation.id,
                    client_request_id=request_id,
                    state=QuoSendAttemptState.ACCEPTED,
                    message_id=message.id,
                )
            )
            persisted_contact = await db.get(Contact, contact.id)
            assert persisted_contact is not None
            persisted_contact.sms_consent_status = "opted_out"
            await db.commit()
            message_id = message.id

        async with _db_session() as db:
            persisted = await db.get(Conversation, conversation.id)
            assert persisted is not None
            with (
                patch(
                    "app.services.conversations.conversation_service.OptOutManager.check_opt_out",
                    new=AsyncMock(),
                ) as opt_out_check,
                patch(
                    "app.services.conversations.conversation_service.claim_quo_send_attempt",
                    new=AsyncMock(),
                ) as claim_mock,
            ):
                replay = await ConversationService(db)._send_quo_message(
                    conversation=persisted,
                    workspace_id=workspace.id,
                    body="Already accepted",
                    sender_user_id=1,
                    sender_display_name="Operator",
                    client_request_id=request_id,
                )

            assert replay.id == message_id
            opt_out_check.assert_not_awaited()
            claim_mock.assert_not_awaited()
    finally:
        await _cleanup(workspace.id)


@pytest.mark.parametrize("global_opt_out", [False, True])
async def test_contact_or_global_opt_out_blocks_before_attempt(
    global_opt_out: bool,
) -> None:
    workspace, _contact, conversation = await _records(
        f"Quo opt-out {global_opt_out}",
        consent_status="unknown" if global_opt_out else "opted_out",
    )
    try:
        async with _db_session() as db:
            persisted = await db.get(Conversation, conversation.id)
            assert persisted is not None
            with (
                patch(
                    "app.services.conversations.conversation_service.OptOutManager.check_opt_out",
                    new=AsyncMock(return_value=global_opt_out),
                ),
                patch(
                    "app.services.conversations.conversation_service.claim_quo_send_attempt",
                    new=AsyncMock(),
                ) as claim_mock,
                pytest.raises(HTTPException) as exc_info,
            ):
                await ConversationService(db)._send_quo_message(
                    conversation=persisted,
                    workspace_id=workspace.id,
                    body="Must not send",
                    sender_user_id=1,
                    sender_display_name="Operator",
                    client_request_id=uuid.uuid4(),
                )

            assert exc_info.value.status_code == 403
            claim_mock.assert_not_awaited()
    finally:
        await _cleanup(workspace.id)


async def test_quo_ai_and_followup_actions_fail_before_provider_io() -> None:
    workspace, _contact, conversation = await _records(
        "Quo manual only",
        consent_status="opted_in",
    )
    try:
        async with _db_session() as db:
            service = ConversationService(db)
            with patch(
                "app.services.conversations.conversation_service.get_text_message_provider"
            ) as get_provider:
                with pytest.raises(HTTPException) as ai_error:
                    await service.toggle_ai(conversation.id, workspace.id, True)
                with pytest.raises(HTTPException) as followup_error:
                    await service.send_followup(
                        conversation.id,
                        workspace.id,
                        message="Automated follow-up",
                    )

            assert ai_error.value.status_code == 409
            assert followup_error.value.status_code == 409
            get_provider.assert_not_called()
    finally:
        await _cleanup(workspace.id)


async def test_switching_active_line_controls_list_detail_and_timeline_visibility() -> None:
    workspace, contact, active_conversation = await _records(
        "Quo active-line reads",
        consent_status="opted_in",
    )
    old_phone = "+14155552673"
    try:
        async with _db_session() as db:
            old_conversation = Conversation(
                workspace_id=workspace.id,
                contact_id=contact.id,
                channel=MessageChannel.SMS,
                contact_phone=CONTACT_PHONE,
                workspace_phone=old_phone,
                source_provider="quo",
                ai_enabled=False,
                unread_count=3,
            )
            persisted_active = await db.get(Conversation, active_conversation.id)
            assert persisted_active is not None
            persisted_active.unread_count = 2
            db.add(old_conversation)
            await db.flush()
            db.add_all(
                [
                    Message(
                        conversation_id=active_conversation.id,
                        channel=MessageChannel.SMS,
                        direction=MessageDirection.INBOUND,
                        status=MessageStatus.RECEIVED,
                        body="Active line",
                        source_provider="quo",
                    ),
                    Message(
                        conversation_id=old_conversation.id,
                        channel=MessageChannel.SMS,
                        direction=MessageDirection.INBOUND,
                        status=MessageStatus.RECEIVED,
                        body="Old line",
                        source_provider="quo",
                    ),
                ]
            )
            await db.commit()
            old_conversation_id = old_conversation.id

        async with _db_session() as db:
            service = ConversationService(db)
            page = await service.list_conversations(workspace.id)
            assert {item.id for item in page.items} == {active_conversation.id}
            assert (await service.get_unread_summary(workspace.id)).unread_messages == 2
            active_timeline = await get_contact_timeline(
                workspace_id=workspace.id,
                contact_id=contact.id,
                current_user=MagicMock(),
                db=db,
                membership=MagicMock(),
                limit=100,
                conversation_id=None,
            )
            assert [item.content for item in active_timeline if item.type == "sms"] == [
                "Active line"
            ]
            assert (await service.mark_all_read(workspace.id)).conversations_marked == 1
            with pytest.raises(HTTPException) as detail_error:
                await service._get_conversation(old_conversation_id, workspace.id)
            assert detail_error.value.status_code == 404
            with pytest.raises(HTTPException) as timeline_error:
                await get_contact_timeline(
                    workspace_id=workspace.id,
                    contact_id=contact.id,
                    current_user=MagicMock(),
                    db=db,
                    membership=MagicMock(),
                    limit=100,
                    conversation_id=old_conversation_id,
                )
            assert timeline_error.value.status_code == 404

            integration = await db.scalar(
                select(WorkspaceIntegration).where(
                    WorkspaceIntegration.workspace_id == workspace.id,
                    WorkspaceIntegration.integration_type == "quo",
                )
            )
            assert integration is not None
            integration.credentials = {
                "api_key": "quo_test_key",
                "phone_number_id": "PN_old",
                "phone_number": old_phone,
            }
            await db.commit()

            page = await service.list_conversations(workspace.id)
            assert {item.id for item in page.items} == {old_conversation_id}
            assert (await service.get_unread_summary(workspace.id)).unread_messages == 3
            assert await service._get_conversation(old_conversation_id, workspace.id)
            timeline = await get_contact_timeline(
                workspace_id=workspace.id,
                contact_id=contact.id,
                current_user=MagicMock(),
                db=db,
                membership=MagicMock(),
                limit=100,
                conversation_id=old_conversation_id,
            )
            assert [item.content for item in timeline if item.type == "sms"] == ["Old line"]
            switched_timeline = await get_contact_timeline(
                workspace_id=workspace.id,
                contact_id=contact.id,
                current_user=MagicMock(),
                db=db,
                membership=MagicMock(),
                limit=100,
                conversation_id=None,
            )
            assert [item.content for item in switched_timeline if item.type == "sms"] == [
                "Old line"
            ]
            assert (
                await db.scalar(
                    select(func.count(Conversation.id)).where(
                        Conversation.workspace_id == workspace.id
                    )
                )
                == 2
            )
    finally:
        await _cleanup(workspace.id)


async def test_other_workspace_integration_or_sender_line_cannot_be_used() -> None:
    workspace, _contact, conversation = await _records(
        "Quo wrong selected line",
        consent_status="opted_in",
        selected_phone="+14155550199",
    )
    other_workspace, _other_contact, _other_conversation = await _records(
        "Quo other workspace",
        consent_status="opted_in",
    )
    try:
        async with _db_session() as db:
            persisted = await db.get(Conversation, conversation.id)
            assert persisted is not None
            with (
                patch(
                    "app.services.conversations.conversation_service.claim_quo_send_attempt",
                    new=AsyncMock(),
                ) as claim_mock,
                pytest.raises(HTTPException) as exc_info,
            ):
                await ConversationService(db)._send_quo_message(
                    conversation=persisted,
                    workspace_id=workspace.id,
                    body="Wrong line",
                    sender_user_id=1,
                    sender_display_name="Operator",
                    client_request_id=uuid.uuid4(),
                )

            assert exc_info.value.status_code == 409
            claim_mock.assert_not_awaited()

            await db.execute(
                delete(WorkspaceIntegration).where(
                    WorkspaceIntegration.workspace_id == workspace.id
                )
            )
            await db.commit()
            with (
                patch(
                    "app.services.conversations.conversation_service.claim_quo_send_attempt",
                    new=AsyncMock(),
                ) as other_claim_mock,
                pytest.raises(HTTPException) as other_exc,
            ):
                await ConversationService(db)._send_quo_message(
                    conversation=persisted,
                    workspace_id=workspace.id,
                    body="Other tenant integration",
                    sender_user_id=1,
                    sender_display_name="Operator",
                    client_request_id=uuid.uuid4(),
                )
            assert other_exc.value.status_code == 409
            other_claim_mock.assert_not_awaited()
    finally:
        await _cleanup(workspace.id)
        await _cleanup(other_workspace.id)
