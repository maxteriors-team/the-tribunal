"""Human contact edits feed durable AI memory in the same transaction."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.contact_ai_memory_service import ContactAIMemoryService
from app.services.contacts import contact_repository


@pytest.mark.asyncio
async def test_human_contact_edit_records_relevant_memory_fact_before_commit() -> None:
    workspace_id = uuid.uuid4()
    contact = SimpleNamespace(
        id=17,
        workspace_id=workspace_id,
        notes="Old note",
    )
    db = MagicMock()
    db.commit = AsyncMock()

    with (
        patch.object(
            contact_repository,
            "get_contact_by_id",
            new=AsyncMock(return_value=contact),
        ),
        patch.object(
            ContactAIMemoryService,
            "record_contact_edit",
            new=AsyncMock(return_value=MagicMock()),
        ) as record_edit,
    ):
        updated = await contact_repository.update_contact(
            contact=contact,
            update_data={"notes": "Customer prefers text follow-up"},
            db=db,
        )

    assert updated is contact
    assert contact.notes == "Customer prefers text follow-up"
    kwargs = record_edit.await_args.kwargs
    assert kwargs["workspace_id"] == workspace_id
    assert kwargs["contact_id"] == 17
    assert kwargs["changed_fields"] == {"notes": "Customer prefers text follow-up"}
    assert kwargs["provenance_event_id"].startswith("contact-edit:")
    record_order = [call[0] for call in db.mock_calls if call[0] in {"commit"}]
    assert record_order == ["commit"]
