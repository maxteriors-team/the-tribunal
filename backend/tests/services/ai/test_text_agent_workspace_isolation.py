"""Inbound AI resolves conversations and agents inside the supplied workspace."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql import Select

from app.services.ai.text_agent import process_inbound_with_ai


def _result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _assert_workspace_scoped(query: object, workspace_id: uuid.UUID) -> None:
    assert isinstance(query, Select)
    sql = str(query.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "workspace_id" in sql
    assert workspace_id.hex in sql


@pytest.mark.asyncio
async def test_inbound_conversation_lookup_is_workspace_scoped() -> None:
    workspace_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(None))

    await process_inbound_with_ai(uuid.uuid4(), workspace_id, db, response_started_at=0)

    _assert_workspace_scoped(db.execute.await_args.args[0], workspace_id)


@pytest.mark.asyncio
async def test_imported_inbound_never_reaches_ai_agent_lookup() -> None:
    workspace_id = uuid.uuid4()
    conversation = SimpleNamespace(
        source_provider="legacy_import",
        ai_enabled=True,
        ai_paused=False,
        assigned_agent_id=uuid.uuid4(),
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(conversation))

    await process_inbound_with_ai(uuid.uuid4(), workspace_id, db, response_started_at=0)

    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_inbound_agent_lookup_is_workspace_scoped() -> None:
    workspace_id = uuid.uuid4()
    conversation = SimpleNamespace(
        ai_enabled=True,
        ai_paused=False,
        assigned_agent_id=uuid.uuid4(),
    )
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_result(conversation), _result(None)])

    await process_inbound_with_ai(uuid.uuid4(), workspace_id, db, response_started_at=0)

    _assert_workspace_scoped(db.execute.await_args_list[1].args[0], workspace_id)
