"""Tests for contact timeline service."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.models.contact import Contact
from app.services.contacts.exceptions import ContactNotFoundError
from app.services.contacts.timeline_service import ContactTimelineService


class TestContactTimelineService:
    """Timeline behavior extracted from ContactService."""

    async def test_timeline_verifies_contact_and_delegates_repository(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace_id = uuid.uuid4()
        contact_id = 42
        now = datetime.now(UTC)
        contact = Contact(
            id=contact_id,
            workspace_id=workspace_id,
            first_name="Alice",
            phone_number="+14155551234",
            status="new",
        )
        timeline = [
            {"id": uuid.uuid4(), "timestamp": now - timedelta(minutes=1), "content": "Hi"},
            {"id": uuid.uuid4(), "timestamp": now, "content": "Hello"},
        ]
        captured: dict[str, object] = {}

        async def fake_get_contact_by_id(
            lookup_contact_id: int,
            lookup_workspace_id: uuid.UUID,
            db: object,
        ) -> Contact | None:
            captured["lookup_contact_id"] = lookup_contact_id
            captured["lookup_workspace_id"] = lookup_workspace_id
            captured["lookup_db"] = db
            return contact

        async def fake_get_contact_timeline(**kwargs: object) -> list[dict[str, object]]:
            captured.update(kwargs)
            return timeline

        monkeypatch.setattr(
            "app.services.contacts.timeline_service.get_contact_by_id",
            fake_get_contact_by_id,
        )
        monkeypatch.setattr(
            "app.services.contacts.timeline_service.repo_get_contact_timeline",
            fake_get_contact_timeline,
        )

        db = AsyncMock()
        conversation_id = uuid.uuid4()
        result = await ContactTimelineService(db).get_contact_timeline(
            contact_id=contact_id,
            workspace_id=workspace_id,
            limit=25,
            conversation_id=conversation_id,
        )

        assert result == timeline
        assert captured["lookup_contact_id"] == contact_id
        assert captured["lookup_workspace_id"] == workspace_id
        assert captured["lookup_db"] == db
        assert captured["contact_id"] == contact_id
        assert captured["workspace_id"] == workspace_id
        assert captured["limit"] == 25
        assert captured["conversation_id"] == conversation_id

    async def test_timeline_raises_when_contact_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_get_contact_by_id(
            lookup_contact_id: int,
            lookup_workspace_id: uuid.UUID,
            db: object,
        ) -> None:
            return None

        repo_mock = AsyncMock()
        monkeypatch.setattr(
            "app.services.contacts.timeline_service.get_contact_by_id",
            fake_get_contact_by_id,
        )
        monkeypatch.setattr(
            "app.services.contacts.timeline_service.repo_get_contact_timeline",
            repo_mock,
        )

        with pytest.raises(ContactNotFoundError):
            await ContactTimelineService(AsyncMock()).get_contact_timeline(
                contact_id=99,
                workspace_id=uuid.uuid4(),
            )

        repo_mock.assert_not_awaited()
