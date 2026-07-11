"""Tests for the CRM tool executor — workspace scoping + dispatch."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tools import CRM_TOOLS, get_crm_tools


@pytest.mark.asyncio
async def test_tool_spec_handler_parity() -> None:
    """Every tool defined in _tools.py must have a handler in the executor.

    Rather than hard-coding the expected handler set (which silently rots
    every time we add or rename a tool), drive the assertion off ``execute``
    itself: dispatching a tool with an empty arg payload must not return the
    ``Unknown function`` sentinel. Handlers may fail for other reasons
    (missing DB rows, validation errors) — that's fine. We only care that
    the dispatcher knows the name.
    """
    spec_names = {t["function"]["name"] for t in get_crm_tools()}
    assert spec_names, "CRM tool registry is empty"
    assert len(CRM_TOOLS) == len(spec_names)

    # ``db.execute`` is awaited by some handlers before they validate args; a
    # blanket ``AsyncMock`` keeps that happy without leaking real I/O.
    executor = CRMToolExecutor(db=AsyncMock(), workspace_id=uuid.uuid4(), user_id=1)
    assert executor.workspace_id is not None

    for name in spec_names:
        result = await executor.execute(name, {})
        # We allow handlers to fail (success=False) but the dispatcher must
        # not say it doesn't know the name.
        error = result.get("error") or ""
        assert not error.startswith("Unknown function"), (
            f"Tool spec declares {name!r} but executor has no handler: {result!r}"
        )


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error() -> None:
    """Unknown tool names should return a structured error, not raise."""
    executor = CRMToolExecutor(db=AsyncMock(), workspace_id=uuid.uuid4(), user_id=1)
    result = await executor.execute("nonexistent_tool", {})
    assert result["success"] is False
    assert "Unknown function" in result["error"]


@pytest.mark.asyncio
async def test_execute_handler_exception_returns_error() -> None:
    """Handler exceptions are caught and surfaced as success=False."""
    workspace_id = uuid.uuid4()

    # Mock db.execute to raise inside the handler
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("db down")

    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=1)
    result = await executor.execute("search_contacts", {"query": "x"})
    assert result["success"] is False
    assert "search_contacts" in result["error"]


@pytest.mark.asyncio
async def test_search_contacts_filters_by_workspace() -> None:
    """The contacts search must scope to the given workspace_id."""
    workspace_id = uuid.uuid4()

    captured_stmts: list[Any] = []

    async def fake_execute(stmt: Any) -> Any:
        captured_stmts.append(stmt)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    db = AsyncMock()
    db.execute = fake_execute  # type: ignore[assignment]

    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=1)
    out = await executor.execute("search_contacts", {"query": "alice"})

    assert out["success"] is True
    assert out["count"] == 0
    # The bound parameters must include the workspace_id (multi-tenant scoping).
    assert len(captured_stmts) == 1
    compiled = captured_stmts[0].compile()
    assert workspace_id in compiled.params.values()


@pytest.mark.asyncio
async def test_search_contacts_returns_dated_followup_evidence() -> None:
    """Search results expose enough dated CRM evidence for grounded recommendations."""
    now = datetime(2026, 7, 10, 15, 30, tzinfo=UTC)
    contact = SimpleNamespace(
        id=7,
        first_name="Ava",
        last_name="Rivera",
        phone_number="+15555550123",
        email="ava@example.com",
        status="qualified",
        company_name="Rivera Co",
        lead_score=88,
        engagement_score=73,
        is_qualified=True,
        qualification_signals={"interest_level": "high", "next_steps": "Send estimate"},
        source="inbound_sms",
        last_appointment_status="completed",
        last_engaged_at=now,
        created_at=now,
        updated_at=now,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [contact]
    db = AsyncMock()
    db.execute.return_value = result
    executor = CRMToolExecutor(db=db, workspace_id=uuid.uuid4(), user_id=1)

    response = await executor.execute("search_contacts", {"query": "Ava", "limit": 5})

    evidence = response["data"][0]
    assert evidence["lead_score"] == 88
    assert evidence["engagement_score"] == 73
    assert evidence["qualification_signals"]["next_steps"] == "Send estimate"
    assert evidence["last_engaged_at"] == now.isoformat()
    assert evidence["updated_at"] == now.isoformat()
