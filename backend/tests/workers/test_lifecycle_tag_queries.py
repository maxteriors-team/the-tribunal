"""Tests for lifecycle workers using normalized ContactTag predicates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.workers.automation_worker import AutomationWorker
from app.workers.never_booked_worker import NeverBookedWorker
from app.workers.noshow_reengagement_worker import NoshowReengagementWorker


def _capture_db() -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    return db


async def test_automation_contact_tagged_uses_normalized_join() -> None:
    """The contact-tagged trigger no longer depends on contacts.tags ARRAY."""
    db = _capture_db()
    worker = AutomationWorker()

    await worker._contacts_tagged(
        base_filters=[],
        tag_name="warm-lead",
        since=datetime(2026, 1, 1, tzinfo=UTC),
        db=db,
    )

    sql = str(db.execute.await_args.args[0])
    assert "JOIN contact_tags" in sql
    assert "JOIN tags" in sql
    assert "contacts.tags" not in sql


async def test_never_booked_query_excludes_normalized_lifecycle_tags() -> None:
    """Never-booked suppression checks ContactTag/Tag instead of the dropped array."""
    db = _capture_db()
    worker = NeverBookedWorker()
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.workspace_id = uuid.uuid4()
    agent.never_booked_delay_days = 7

    await worker._process_agent(agent, db)

    sql = str(db.execute.await_args_list[0].args[0])
    assert "contact_tags" in sql
    assert "tags" in sql
    assert "appointment-scheduled" not in sql  # bound parameter, not literal SQL
    assert "contacts.tags" not in sql


def test_noshow_tag_predicates_use_normalized_tables() -> None:
    """No-show sequence helpers build EXISTS clauses against normalized tables."""
    workspace_id = uuid.uuid4()

    sql = str(NoshowReengagementWorker._has_any_tag(workspace_id, ["no-show"]))

    assert "contact_tags" in sql
    assert "tags" in sql
    assert "contacts.tags" not in sql
