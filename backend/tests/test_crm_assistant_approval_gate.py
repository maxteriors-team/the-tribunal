"""The approval gate must not be reachable from model-written arguments.

The gate used to read ``args.get("confirmed")``, and ``confirmed`` was a
declared parameter in the tool schema the model writes. Nothing required a
human: the model could emit ``confirmed: true`` itself and walk straight past
approval on send_sms, start_campaign, create_automation and create_agent.
``user_confirmed`` was honoured too and appeared in no schema at all.

Approval state now lives only in the executor and the /pending-actions flow.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tool_metadata import (
    CRM_ASSISTANT_ACTION_PREFIX,
    get_tool_policy,
)
from app.services.ai.crm_assistant._tools import get_crm_tools

# Every tool that can spend money, message a customer, or change AI behaviour.
GATED_TOOLS = (
    "send_sms",
    "send_initial_message",
    "start_campaign",
    "resume_campaign",
    "create_automation",
    "enable_automation",
    "create_agent",
    "update_agent",
    "assign_ai_responder",
)


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.scalar = AsyncMock(return_value=0)
    return session


def _executor(db: MagicMock) -> CRMToolExecutor:
    return CRMToolExecutor(db=db, workspace_id=uuid.uuid4(), user_id=7)


def _payload_for(tool: str) -> dict[str, Any]:
    return {
        "send_sms": {"contact_id": 1, "body": "hi"},
        "send_initial_message": {"campaign_id": str(uuid.uuid4()), "contact_id": 1},
        "start_campaign": {"campaign_id": str(uuid.uuid4())},
        "resume_campaign": {"campaign_id": str(uuid.uuid4())},
        "create_automation": {
            "name": "x",
            "trigger_type": "missed_call",
            "actions": [{"type": "send_sms", "config": {"message": "hi"}}],
        },
        "enable_automation": {"automation_id": str(uuid.uuid4())},
        "create_agent": {"name": "x", "system_prompt": "y"},
        "update_agent": {"agent_id": str(uuid.uuid4()), "name": "x"},
        "assign_ai_responder": {
            "conversation_id": str(uuid.uuid4()),
            "agent_id": str(uuid.uuid4()),
        },
    }[tool]


class TestSchemaExposesNoApprovalFlag:
    def test_no_tool_schema_mentions_an_approval_flag(self) -> None:
        payload = json.dumps(get_crm_tools())

        assert "confirmed" not in payload
        assert "user_confirmed" not in payload

    @pytest.mark.parametrize("tool", GATED_TOOLS)
    def test_gated_tools_expose_no_approval_property(self, tool: str) -> None:
        schema = next(
            item["function"] for item in get_crm_tools() if item["function"]["name"] == tool
        )
        properties = schema["parameters"].get("properties", {})

        assert "confirmed" not in properties
        assert "user_confirmed" not in properties

    @pytest.mark.parametrize("tool", GATED_TOOLS)
    def test_gated_tools_still_require_approval_in_policy(self, tool: str) -> None:
        assert get_tool_policy(tool).requires_approval is True


class TestForgedFlagsCannotBypassTheGate:
    @pytest.mark.parametrize("tool", GATED_TOOLS)
    @pytest.mark.parametrize("flag", ["confirmed", "user_confirmed"])
    async def test_model_supplied_flag_still_queues_for_approval(
        self, db: MagicMock, tool: str, flag: str
    ) -> None:
        result = await _executor(db).execute(tool, {**_payload_for(tool), flag: True})

        assert result["success"] is False
        assert result["pending_approval"] is True, f"{tool} bypassed approval via {flag}"

    async def test_forged_flag_is_stripped_from_the_queued_payload(self, db: MagicMock) -> None:
        await _executor(db).execute(
            "start_campaign",
            {"campaign_id": str(uuid.uuid4()), "confirmed": True, "user_confirmed": True},
        )

        queued = db.add.call_args.args[0]
        assert "confirmed" not in queued.action_payload
        assert "user_confirmed" not in queued.action_payload

    async def test_both_flags_together_still_do_not_bypass(self, db: MagicMock) -> None:
        result = await _executor(db).execute(
            "send_sms",
            {"contact_id": 1, "body": "hi", "confirmed": True, "user_confirmed": True},
        )

        assert result["pending_approval"] is True

    async def test_forged_flag_never_reaches_the_handler(self, db: MagicMock) -> None:
        """Even on an ungated tool, the flags are stripped before dispatch."""
        executor = _executor(db)
        seen: list[dict[str, Any]] = []

        async def spy(args: dict[str, Any]) -> dict[str, Any]:
            seen.append(args)
            return {"success": True}

        executor.tool_metadata["list_campaigns"] = replace(
            executor.tool_metadata["list_campaigns"], handler=spy
        )

        await executor.execute("list_campaigns", {"limit": 5, "confirmed": True})

        assert seen == [{"limit": 5}]


class TestApprovedPathStillExecutes:
    async def test_keyword_argument_grants_approval(self, db: MagicMock) -> None:
        executor = _executor(db)

        async def handler(_args: dict[str, Any]) -> dict[str, Any]:
            return {"success": True, "ran": True}

        executor.tool_metadata["start_campaign"] = replace(
            executor.tool_metadata["start_campaign"], handler=handler
        )

        result = await executor.execute(
            "start_campaign", {"campaign_id": str(uuid.uuid4())}, approval_granted=True
        )

        assert result == {"success": True, "ran": True}

    async def test_approval_grant_is_not_expressible_as_tool_json(self) -> None:
        """The only door is a Python keyword the model cannot write."""
        payload = json.dumps(get_crm_tools())

        assert "approval_granted" not in payload

    def test_every_gated_tool_has_an_approved_executor(self) -> None:
        from app.services.ai.crm_assistant._tool_metadata import get_approved_action_executor

        for tool in GATED_TOOLS:
            executor = get_approved_action_executor(f"{CRM_ASSISTANT_ACTION_PREFIX}{tool}")
            assert executor is not None, f"{tool} can be queued but never executed"
