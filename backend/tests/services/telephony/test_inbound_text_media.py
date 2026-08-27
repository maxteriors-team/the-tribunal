"""Media-only behavior in the shared inbound text pipeline."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import MessageChannel
from app.services.telephony import inbound_text
from app.services.telephony.inbound_text import (
    InboundMessageIngestResult,
    InboundTextEvent,
)


class _Result:
    def __init__(self, scalar: object) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar


async def test_media_only_reply_skips_text_interpreters_and_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    conversation = MagicMock(
        id=conversation_id,
        contact_id=None,
        ai_enabled=True,
        ai_paused=False,
    )
    message = MagicMock(id=uuid.uuid4(), conversation_id=conversation_id)
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result(conversation))

    command_processor = MagicMock()
    command_processor.try_process_command = AsyncMock(return_value=False)
    operator_checker = AsyncMock(return_value=None)
    ingest_message = AsyncMock(return_value=InboundMessageIngestResult(message, created=True))
    conversation_syncer = MagicMock()
    conversation_syncer.sync_conversation = AsyncMock(return_value=None)
    schedule_ai = AsyncMock(return_value=None)
    push_service = MagicMock()
    push_service.send_to_workspace_members = AsyncMock(return_value=True)
    monkeypatch.setattr(inbound_text, "_pause_drip_enrollments", AsyncMock())
    monkeypatch.setattr(inbound_text, "_handle_campaign_reply", AsyncMock())

    event = InboundTextEvent(
        provider_message_id="message-media-only",
        from_number="+14155552671",
        to_number="+12125550101",
        body="",
        workspace_id=workspace_id,
        channel=MessageChannel.SMS,
        media_count=1,
        media_preview="Photo received",
    )

    result = await inbound_text.process_inbound_text_event(
        db=db,
        event=event,
        ingest_message=ingest_message,
        log=MagicMock(),
        command_processor=command_processor,
        conversation_syncer=conversation_syncer,
        schedule_ai_response_fn=schedule_ai,
        push_service=push_service,
        check_operator_fn=operator_checker,
    )

    assert result is message
    command_processor.try_process_command.assert_not_awaited()
    operator_checker.assert_not_awaited()
    ingest_message.assert_awaited_once_with(db, event)
    conversation_syncer.sync_conversation.assert_awaited_once()
    schedule_ai.assert_not_awaited()


async def test_duplicate_inbound_message_skips_ai_and_notification_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    message = MagicMock(id=uuid.uuid4(), conversation_id=uuid.uuid4())
    db = MagicMock()
    db.execute = AsyncMock()
    command_processor = MagicMock()
    command_processor.try_process_command = AsyncMock(return_value=False)
    operator_checker = AsyncMock(return_value=None)
    ingest_message = AsyncMock(return_value=InboundMessageIngestResult(message, created=False))
    conversation_syncer = MagicMock()
    conversation_syncer.sync_conversation = AsyncMock()
    schedule_ai = AsyncMock()
    push_service = MagicMock()
    push_service.send_to_workspace_members = AsyncMock()
    pause_drips = AsyncMock()
    campaign_reply = AsyncMock()
    monkeypatch.setattr(inbound_text, "_pause_drip_enrollments", pause_drips)
    monkeypatch.setattr(inbound_text, "_handle_campaign_reply", campaign_reply)

    result = await inbound_text.process_inbound_text_event(
        db=db,
        event=InboundTextEvent(
            provider_message_id="message-duplicate",
            from_number="+14155552671",
            to_number="+12125550101",
            body="Can we book?",
            workspace_id=workspace_id,
            channel=MessageChannel.SMS,
        ),
        ingest_message=ingest_message,
        log=MagicMock(),
        command_processor=command_processor,
        conversation_syncer=conversation_syncer,
        schedule_ai_response_fn=schedule_ai,
        push_service=push_service,
        check_operator_fn=operator_checker,
    )

    assert result is message
    schedule_ai.assert_not_awaited()
    conversation_syncer.sync_conversation.assert_not_awaited()
    pause_drips.assert_not_awaited()
    campaign_reply.assert_not_awaited()
    push_service.send_to_workspace_members.assert_not_awaited()
