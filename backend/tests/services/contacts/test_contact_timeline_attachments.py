"""Timeline serialization tests for message metadata and source provenance."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import Message, MessageChannel, MessageDirection, MessageStatus
from app.models.message_attachment import MESSAGE_ATTACHMENT_READY
from app.schemas.contact import TimelineItem
from app.services.contacts import contact_repository


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)

    def scalar_one_or_none(self) -> object | None:
        return self._values[0] if self._values else None


async def test_contact_timeline_includes_attachment_metadata_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    message_id = uuid.uuid4()
    conversation = SimpleNamespace(id=uuid.uuid4())
    message = SimpleNamespace(
        id=message_id,
        channel="sms",
        created_at=datetime.now(UTC),
        direction="inbound",
        is_ai=False,
        sender_user_id=None,
        sender_display_name=None,
        body="",
        duration_seconds=None,
        recording_url=None,
        transcript=None,
        status="received",
        source_provider="legacy_import",
        external_url="https://archive.example/messages/example",
        is_voicemail=False,
        booking_outcome=None,
        call_outcome=None,
    )
    attachment = SimpleNamespace(
        id=uuid.uuid4(),
        message_id=message_id,
        provider_position=0,
        filename="mms-1.jpg",
        provider_content_type="image/jpeg",
        provider_size_bytes=321,
        content_type="image/jpeg",
        size_bytes=321,
        status=MESSAGE_ATTACHMENT_READY,
    )
    contact = SimpleNamespace(phone_number="+14155552671")
    monkeypatch.setattr(
        contact_repository,
        "get_contact_by_id",
        AsyncMock(return_value=contact),
    )
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _Result([conversation]),
            _Result([message]),
            _Result([attachment]),
        ]
    )

    timeline = await contact_repository.get_contact_timeline(
        contact_id=42,
        workspace_id=workspace_id,
        db=db,
    )

    assert len(timeline) == 1
    item = TimelineItem.model_validate(timeline[0])
    assert item.content == ""
    assert item.source_provider == "legacy_import"
    assert item.external_url == "https://archive.example/messages/example"
    assert item.is_voicemail is False
    assert timeline[0]["attachments"] == [
        {
            "id": attachment.id,
            "filename": "mms-1.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 321,
            "status": MESSAGE_ATTACHMENT_READY,
            "content_url": (
                f"/api/v1/workspaces/{workspace_id}/contacts/42/"
                f"timeline/attachments/{attachment.id}/content"
            ),
        }
    ]
    assert db.execute.await_count == 3


@pytest.mark.parametrize(
    ("sender_user_id", "sender_display_name"),
    [(314, "Jordan Lee"), (None, None)],
    ids=["attributed-human", "historical-outbound"],
)
async def test_contact_timeline_populates_nullable_sender_from_message(
    monkeypatch: pytest.MonkeyPatch,
    sender_user_id: int | None,
    sender_display_name: str | None,
) -> None:
    workspace_id = uuid.uuid4()
    conversation = SimpleNamespace(id=uuid.uuid4())
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        channel=MessageChannel.SMS,
        direction=MessageDirection.OUTBOUND,
        body="Sent by a teammate",
        status=MessageStatus.SENT,
        is_ai=False,
        sender_user_id=sender_user_id,
        sender_display_name=sender_display_name,
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        contact_repository,
        "get_contact_by_id",
        AsyncMock(return_value=SimpleNamespace(phone_number="+14155552671")),
    )
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _Result([conversation]),
            _Result([message]),
        ]
    )

    timeline = await contact_repository.get_contact_timeline(
        contact_id=42,
        workspace_id=workspace_id,
        db=db,
        include_attachments=False,
        include_call_outcomes=False,
    )

    assert len(timeline) == 1
    assert {"sender_user_id", "sender_display_name"} <= timeline[0].keys()
    assert timeline[0]["sender_user_id"] == sender_user_id
    assert timeline[0]["sender_display_name"] == sender_display_name

    item = TimelineItem.model_validate(timeline[0])
    assert item.model_dump(include={"sender_user_id", "sender_display_name"}) == {
        "sender_user_id": sender_user_id,
        "sender_display_name": sender_display_name,
    }
    assert db.execute.await_count == 2
