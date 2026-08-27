"""Inbound Telnyx MMS persistence tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.models.conversation import Message
from app.models.message_attachment import MessageAttachment
from app.services.messaging.outbound_media import OutboundMedia
from app.services.telephony.telnyx import InboundMedia, TelnyxSMSService


class _Result:
    def __init__(self, message: Message | None = None) -> None:
        self.message = message

    def scalar_one_or_none(self) -> Message | None:
        return self.message


async def test_inbound_mms_persists_message_and_media_queue_atomically() -> None:
    workspace_id = uuid.uuid4()
    conversation = MagicMock()
    conversation.id = uuid.uuid4()
    conversation.contact_id = None
    conversation.last_message_preview = None
    conversation.last_message_at = None
    conversation.last_message_direction = None
    conversation.unread_count = 0
    conversation.first_inbound_at = None

    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result())
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    async def assign_message_id() -> None:
        for call in db.add.call_args_list:
            candidate = call.args[0]
            if isinstance(candidate, Message) and candidate.id is None:
                candidate.id = uuid.uuid4()

    db.flush = AsyncMock(side_effect=assign_message_id)

    service = TelnyxSMSService("test-api-key")
    service._get_or_create_conversation = AsyncMock(return_value=conversation)  # type: ignore[method-assign]
    media = (
        InboundMedia(
            source_url="https://media.telnyx.com/inbound/photo.jpg?token=opaque",
            content_type="image/jpeg",
            size_bytes=321,
            sha256="a" * 64,
        ),
        InboundMedia(
            source_url="https://media.telnyx.com/inbound/video.mp4?token=opaque",
            content_type="video/mp4",
            size_bytes=654,
        ),
    )

    ingest_result = await service.process_inbound_message(
        db=db,
        provider_message_id="message-with-media",
        from_number="+14155552671",
        to_number="+12125550101",
        body="",
        workspace_id=workspace_id,
        media=media,
    )
    message = ingest_result.message
    assert ingest_result.created is True

    added = [call.args[0] for call in db.add.call_args_list]
    attachments = [item for item in added if isinstance(item, MessageAttachment)]
    assert message in added
    assert len(attachments) == 2
    assert all(attachment.message_id == message.id for attachment in attachments)
    assert all(attachment.workspace_id == workspace_id for attachment in attachments)
    assert [attachment.provider_position for attachment in attachments] == [0, 1]
    assert [attachment.filename for attachment in attachments] == ["mms-1.jpg", "mms-2.mp4"]
    assert attachments[0].source_url == media[0].source_url
    assert attachments[0].provider_sha256 == "a" * 64
    assert conversation.last_message_preview == "[2 media attachments]"
    assert conversation.unread_count == 1
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()


async def test_duplicate_inbound_delivery_reports_existing_message_without_writes() -> None:
    existing = MagicMock(spec=Message)
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result(existing))
    db.add = MagicMock()
    db.commit = AsyncMock()
    service = TelnyxSMSService("test-api-key")

    result = await service.process_inbound_message(
        db=db,
        provider_message_id="message-duplicate",
        from_number="+14155552671",
        to_number="+12125550101",
        body="Hello",
        workspace_id=uuid.uuid4(),
    )

    assert result.message is existing
    assert result.created is False
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_outbound_mms_sends_media_url_and_persists_ready_attachment() -> None:
    workspace_id = uuid.uuid4()
    conversation = MagicMock()
    conversation.id = uuid.uuid4()
    conversation.contact_id = None
    conversation.last_message_preview = None
    conversation.last_message_at = None
    conversation.last_message_direction = None

    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result())
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    async def assign_message_id() -> None:
        for call in db.add.call_args_list:
            candidate = call.args[0]
            if isinstance(candidate, Message) and candidate.id is None:
                candidate.id = uuid.uuid4()

    db.flush = AsyncMock(side_effect=assign_message_id)

    service = TelnyxSMSService("test-api-key")
    service._get_or_create_conversation = AsyncMock(return_value=conversation)  # type: ignore[method-assign]
    service._post_message = AsyncMock(return_value={"data": {"id": "outbound-mms-1"}})  # type: ignore[method-assign]
    media = OutboundMedia(
        attachment_id=uuid.uuid4(),
        provider_url="https://storage.example/photo.jpg?signature=short-lived",
        storage_key=f"workspaces/{workspace_id}/outbound-attachments/photo.jpg",
        content_type="image/jpeg",
        size_bytes=321,
        sha256="b" * 64,
        filename="photo.jpg",
    )

    message = await service.send_message(
        to_number="+14155552671",
        from_number="+12125550101",
        body="",
        db=db,
        workspace_id=workspace_id,
        media=(media,),
    )

    payload = service._post_message.await_args.args[0]
    assert payload == {
        "to": "+14155552671",
        "from": "+12125550101",
        "type": "MMS",
        "media_urls": [media.provider_url],
    }
    added = [call.args[0] for call in db.add.call_args_list]
    attachments = [item for item in added if isinstance(item, MessageAttachment)]
    assert len(attachments) == 1
    assert attachments[0].id == media.attachment_id
    assert attachments[0].message_id == message.id
    assert attachments[0].storage_key == media.storage_key
    assert attachments[0].status == "ready"
    assert conversation.last_message_preview == "[Photo]"
    db.commit.assert_awaited_once()
