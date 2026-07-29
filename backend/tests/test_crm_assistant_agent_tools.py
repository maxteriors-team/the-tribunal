"""AI agent read tools expose prompts before updates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.agent import Agent
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tool_metadata import ToolRiskLevel, get_tool_policy
from app.services.ai.crm_assistant._tools import get_crm_tools


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _ExecuteResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._rows)

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=1)
    return session


def _agent(workspace_id: uuid.UUID) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name="Front Desk",
        description="Books appointments",
        channel_mode="both",
        voice_provider="openai",
        voice_id="alloy",
        language="en-US",
        system_prompt="Qualify the caller, then offer an appointment.",
        temperature=0.7,
        enabled_tools=["book_appointment", "transfer_call"],
        is_active=True,
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        updated_at=datetime(2026, 7, 2, tzinfo=UTC),
    )


def test_get_agent_is_registered_as_low_risk() -> None:
    names = {tool["function"]["name"] for tool in get_crm_tools()}

    assert "get_agent" in names
    assert get_tool_policy("get_agent").risk_level == ToolRiskLevel.LOW
    assert get_tool_policy("get_agent").requires_approval is False


async def test_list_agents_includes_prompt_and_enabled_tools(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    agent = _agent(workspace_id)
    db.execute.return_value = _ExecuteResult([agent])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("list_agents", {"limit": 10})

    assert result["returned"] == 1
    assert result["data"][0]["system_prompt"] == agent.system_prompt
    assert result["data"][0]["enabled_tools"] == agent.enabled_tools


async def test_get_agent_returns_prompt_from_workspace_scoped_lookup(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    agent = _agent(workspace_id)
    db.execute.return_value = _ExecuteResult([agent])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("get_agent", {"agent_id": str(agent.id)})

    assert result["success"] is True
    assert result["data"]["system_prompt"] == agent.system_prompt
    assert result["data"]["enabled_tools"] == agent.enabled_tools
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "workspace_id" in compiled
    assert workspace_id.hex in compiled


async def test_get_agent_rejects_an_invalid_id(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("get_agent", {"agent_id": "not-a-uuid"})

    assert result["code"] == "invalid_argument"
    assert "agent_id" in result["message"]
    db.execute.assert_not_awaited()
