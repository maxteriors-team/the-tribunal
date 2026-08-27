"""Unit coverage for conversation unread state.

The database is mocked: these assert the service's contract (what it writes,
what it returns, when it skips the write), not SQL execution.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.workspace import WorkspaceIntegration
from app.services.conversations.conversation_service import ConversationService
from tests.factories import ContactFactory, ConversationFactory


def _db_returning(result: MagicMock) -> AsyncMock:
    db = AsyncMock()
    no_quo_integration = MagicMock()
    no_quo_integration.scalar_one_or_none.return_value = None

    async def execute(statement: Any) -> MagicMock:
        descriptions = getattr(statement, "column_descriptions", ())
        entity = descriptions[0].get("entity") if descriptions else None
        return no_quo_integration if entity is WorkspaceIntegration else result

    db.execute = AsyncMock(side_effect=execute)
    db.commit = AsyncMock()
    return db


class TestGetUnreadSummary:
    """The header badge reads one aggregate row, not a page of threads."""

    async def test_returns_conversation_and_message_counts(self) -> None:
        result = MagicMock()
        result.one = MagicMock(return_value=(3, 7))
        svc = ConversationService(_db_returning(result))

        summary = await svc.get_unread_summary(workspace_id=uuid.uuid4())

        assert summary.unread_conversations == 3
        assert summary.unread_messages == 7

    async def test_empty_workspace_is_zero_not_none(self) -> None:
        """``SUM`` over no rows is coalesced, so the badge never renders ``null``."""
        result = MagicMock()
        result.one = MagicMock(return_value=(0, 0))
        svc = ConversationService(_db_returning(result))

        summary = await svc.get_unread_summary(workspace_id=uuid.uuid4())

        assert summary.unread_conversations == 0
        assert summary.unread_messages == 0


class TestMarkRead:
    """Marking one thread read clears its counter and echoes the thread back."""

    async def test_clears_unread_and_commits(self) -> None:
        contact = ContactFactory.build(first_name="Robin", last_name="Stevanovich")
        conversation = ConversationFactory.build(
            contact=contact, workspace=contact.workspace, unread_count=3
        )
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=conversation)
        db = _db_returning(result)
        svc = ConversationService(db)

        response = await svc.mark_read(
            conversation_id=conversation.id, workspace_id=conversation.workspace_id
        )

        assert conversation.unread_count == 0
        assert response.unread_count == 0
        # The caller patches its cache from this payload, so the label must ride along.
        assert response.contact_name == "Robin Stevanovich"
        db.commit.assert_awaited_once()

    async def test_already_read_thread_skips_the_write(self) -> None:
        """Idempotent: re-marking a read thread must not burn a transaction."""
        conversation = ConversationFactory.build(unread_count=0)
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=conversation)
        db = _db_returning(result)
        svc = ConversationService(db)

        response = await svc.mark_read(
            conversation_id=conversation.id, workspace_id=conversation.workspace_id
        )

        assert response.unread_count == 0
        db.commit.assert_not_awaited()

    async def test_missing_conversation_raises_404(self) -> None:
        from fastapi import HTTPException

        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        svc = ConversationService(_db_returning(result))

        with pytest.raises(HTTPException) as exc_info:
            await svc.mark_read(conversation_id=uuid.uuid4(), workspace_id=uuid.uuid4())

        assert exc_info.value.status_code == 404

    async def test_cross_workspace_thread_is_not_found(self) -> None:
        """The workspace filter is in the query, so a foreign id 404s."""
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        db = _db_returning(result)
        svc = ConversationService(db)
        other_workspace = uuid.uuid4()

        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await svc.mark_read(conversation_id=uuid.uuid4(), workspace_id=other_workspace)

        compiled = str(db.execute.await_args.args[0])
        assert "workspace_id" in compiled


class TestMarkAllRead:
    """Bulk clear reports how many threads it touched."""

    async def test_returns_rowcount(self) -> None:
        result = MagicMock()
        result.rowcount = 4
        db = _db_returning(result)
        svc = ConversationService(db)

        response = await svc.mark_all_read(workspace_id=uuid.uuid4())

        assert response.conversations_marked == 4
        db.commit.assert_awaited_once()

    async def test_none_rowcount_reports_zero(self) -> None:
        """Some drivers report ``None``; the response stays a valid int."""
        result = MagicMock()
        result.rowcount = None
        svc = ConversationService(_db_returning(result))

        response = await svc.mark_all_read(workspace_id=uuid.uuid4())

        assert response.conversations_marked == 0

    async def test_only_touches_unread_rows_in_the_workspace(self) -> None:
        result = MagicMock()
        result.rowcount = 0
        db = _db_returning(result)
        svc = ConversationService(db)

        await svc.mark_all_read(workspace_id=uuid.uuid4())

        compiled = str(db.execute.await_args.args[0])
        assert compiled.startswith("UPDATE conversations")
        assert "workspace_id" in compiled
        assert "unread_count" in compiled
