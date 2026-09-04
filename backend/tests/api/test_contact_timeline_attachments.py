"""Authorization and state handling for private timeline media."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.contacts import get_timeline_attachment_content
from app.models.message_attachment import (
    MESSAGE_ATTACHMENT_FAILED,
    MESSAGE_ATTACHMENT_PENDING,
    MESSAGE_ATTACHMENT_READY,
)


class _Result:
    def __init__(self, scalar: object | None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> object | None:
        return self._scalar


async def test_ready_attachment_redirects_to_short_lived_private_url() -> None:
    workspace_id = uuid.uuid4()
    contact = MagicMock(phone_number="+14155552671")
    attachment = MagicMock(
        status=MESSAGE_ATTACHMENT_READY,
        storage_key="workspaces/ws/messages/msg/attachments/photo.jpg",
    )
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_Result(contact), _Result(attachment)])
    storage = MagicMock()
    storage.create_download_url.return_value = (
        "https://private-bucket.railway.app/photo.jpg?signature=redacted"
    )

    with patch(
        "app.api.v1.contacts.MMSMediaStorage.from_settings",
        return_value=storage,
    ):
        response = await get_timeline_attachment_content(
            workspace_id=workspace_id,
            contact_id=42,
            attachment_id=uuid.uuid4(),
            current_user=MagicMock(),
            db=db,
            membership=MagicMock(),
        )

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://private-bucket.railway.app/")
    assert response.headers["cache-control"] == "private, no-store"
    storage.create_download_url.assert_called_once_with(
        object_key="workspaces/ws/messages/msg/attachments/photo.jpg"
    )


async def test_cross_workspace_or_contact_attachment_returns_not_found() -> None:
    contact = MagicMock(phone_number="+14155552671")
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_Result(contact), _Result(None)])

    with pytest.raises(HTTPException) as exc_info:
        await get_timeline_attachment_content(
            workspace_id=uuid.uuid4(),
            contact_id=42,
            attachment_id=uuid.uuid4(),
            current_user=MagicMock(),
            db=db,
            membership=MagicMock(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Attachment not found"


@pytest.mark.parametrize(
    ("attachment_status", "storage_key", "expected_status"),
    [
        (MESSAGE_ATTACHMENT_PENDING, None, 409),
        (MESSAGE_ATTACHMENT_FAILED, None, 410),
    ],
)
async def test_attachment_processing_state_is_explicit(
    attachment_status: str,
    storage_key: str | None,
    expected_status: int,
) -> None:
    contact = MagicMock(phone_number=None)
    attachment = MagicMock(status=attachment_status, storage_key=storage_key)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_Result(contact), _Result(attachment)])

    with pytest.raises(HTTPException) as exc_info:
        await get_timeline_attachment_content(
            workspace_id=uuid.uuid4(),
            contact_id=42,
            attachment_id=uuid.uuid4(),
            current_user=MagicMock(),
            db=db,
            membership=MagicMock(),
        )

    assert exc_info.value.status_code == expected_status
