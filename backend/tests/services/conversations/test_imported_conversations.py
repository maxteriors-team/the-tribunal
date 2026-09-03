"""Provider-neutral safeguards for imported conversation history."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, status

from app.services.conversations.conversation_service import ConversationService


@pytest.mark.parametrize("source_provider", ["quo", "legacy_import"])
async def test_imported_conversation_send_stops_before_provider_io(
    source_provider: str,
) -> None:
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        source_provider=source_provider,
    )
    service = ConversationService(AsyncMock())

    with (
        patch.object(service, "_get_conversation", AsyncMock(return_value=conversation)),
        patch(
            "app.services.conversations.conversation_service.get_text_message_provider"
        ) as get_provider,
        pytest.raises(HTTPException) as exc_info,
    ):
        await service.send_message(
            conversation.id,
            uuid.uuid4(),
            "This must not leave the app",
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "Imported conversations are read-only"
    get_provider.assert_not_called()


@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        ("toggle_ai", {"enabled": False}),
        ("pause_ai", {}),
        ("resume_ai", {}),
        ("assign_agent", {"agent_id": None}),
        ("clear_history", {}),
        ("update_followup_settings", {"enabled": False}),
        ("reset_followup_counter", {}),
    ],
)
async def test_imported_conversation_mutations_are_rejected(
    method_name: str,
    kwargs: dict[str, object],
) -> None:
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        source_provider="legacy_import",
    )
    service = ConversationService(AsyncMock())

    with (
        patch.object(service, "_get_conversation", AsyncMock(return_value=conversation)),
        pytest.raises(HTTPException) as exc_info,
    ):
        await getattr(service, method_name)(conversation.id, uuid.uuid4(), **kwargs)

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "Imported conversations are read-only"


async def test_historical_imported_conversation_remains_retrievable() -> None:
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        source_provider="quo",
    )
    result = SimpleNamespace(scalar_one_or_none=lambda: conversation)
    db = AsyncMock()
    db.execute.return_value = result
    service = ConversationService(db)

    found = await service._get_conversation(conversation.id, uuid.uuid4())

    assert found is conversation
    where_clause = str(db.execute.await_args.args[0]).split("WHERE", maxsplit=1)[1]
    assert "source_provider" not in where_clause


async def test_imported_conversation_can_still_be_marked_read() -> None:
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        source_provider="legacy_import",
        unread_count=2,
    )
    db = AsyncMock()
    service = ConversationService(db)

    with (
        patch.object(service, "_get_conversation", AsyncMock(return_value=conversation)),
        patch(
            "app.services.conversations.conversation_service.serialize_conversation",
            return_value=conversation,
        ),
    ):
        result = await service.mark_read(conversation.id, uuid.uuid4())

    assert result.unread_count == 0
    db.commit.assert_awaited_once()
