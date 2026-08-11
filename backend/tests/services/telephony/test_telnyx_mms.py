"""Inbound Telnyx MMS persistence tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.models.conversation import Message
from app.models.message_attachment import MessageAttachment
from app.services.telephony.telnyx import InboundMedia, TelnyxSMSService


class _Result:
    def scalar_one_or_none(self) -> None:
        return None


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

    message = await service.process_inbound_message(
        db=db,
        provider_message_id="message-with-media",
        from_number="+14155552671",
        to_number="+12125550101",
        body="",
        workspace_id=workspace_id,
        media=media,
    )

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
