"""Timeline serialization tests for inbound MMS media metadata."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.message_attachment import MESSAGE_ATTACHMENT_READY
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


async def test_contact_timeline_includes_safe_attachment_metadata(
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
        body="",
        duration_seconds=None,
        recording_url=None,
        transcript=None,
        status="received",
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
    assert timeline[0]["content"] == ""
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
