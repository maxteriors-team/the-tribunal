"""Tests for the graceful end-call / hangup voice tool.

The phone agent previously had no way to hang up: it could only fall silent,
leaving the caller in dead air until an idle timeout. ``end_call`` lets the
agent hang up after delivering its farewell, with the actual Telnyx hangup
delayed a few seconds so the goodbye audio finishes playing.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import app.services.ai.tool_executor as tool_executor_module
from app.services.ai.tool_executor import (
    GATE_EXEMPT_TOOLS,
    VoiceToolExecutor,
    _delayed_hangup,
)
from app.services.ai.voice_tools import END_CALL_TOOL, build_tools_list


def _executor(call_control_id: str | None = "ccid-123") -> VoiceToolExecutor:
    agent = object()  # BaseToolExecutor only stores it; end_call never reads it
    return VoiceToolExecutor(
        agent=agent,
        contact_info={"name": "Jamie", "phone": "+15550002222"},
        call_control_id=call_control_id,
        workspace_id=uuid.uuid4(),
    )


def test_end_call_tool_is_present_by_default() -> None:
    tools = build_tools_list()
    names = {t.get("name") for t in tools}
    assert "end_call" in names


def test_end_call_tool_can_be_disabled() -> None:
    tools = build_tools_list(enable_end_call=False)
    names = {t.get("name") for t in tools}
    assert "end_call" not in names


def test_end_call_is_gate_exempt() -> None:
    # Hanging up must never wait on operator approval.
    assert "end_call" in GATE_EXEMPT_TOOLS


def test_end_call_tool_schema_requires_nothing() -> None:
    assert END_CALL_TOOL["name"] == "end_call"
    assert END_CALL_TOOL["parameters"]["required"] == []


async def test_end_call_schedules_delayed_hangup() -> None:
    executor = _executor()
    scheduled: dict[str, Any] = {}

    async def fake_delayed_hangup(**kwargs: Any) -> None:
        scheduled.update(kwargs)

    with (
        patch.object(tool_executor_module.settings, "telnyx_api_key", "KE-test"),
        patch.object(tool_executor_module, "_delayed_hangup", fake_delayed_hangup),
    ):
        result = await executor._execute_end_call(reason="caller said goodbye")
        # Let the scheduled task run.
        await asyncio.sleep(0)

    assert result["success"] is True
    assert scheduled["call_control_id"] == "ccid-123"
    assert scheduled["delay_seconds"] == tool_executor_module.END_CALL_HANGUP_DELAY_SECONDS


async def test_end_call_without_call_control_id_fails() -> None:
    executor = _executor(call_control_id=None)

    with patch.object(tool_executor_module.settings, "telnyx_api_key", "KE-test"):
        result = await executor._execute_end_call()

    assert result["success"] is False
    assert "active call" in result["error"].lower()


async def test_end_call_without_telnyx_key_fails() -> None:
    executor = _executor()

    with patch.object(tool_executor_module.settings, "telnyx_api_key", ""):
        result = await executor._execute_end_call()

    assert result["success"] is False


async def test_delayed_hangup_waits_then_hangs_up() -> None:
    fake_service = AsyncMock()
    fake_service.hangup_call = AsyncMock(return_value=True)
    fake_service.close = AsyncMock()

    with (
        patch.object(tool_executor_module.settings, "telnyx_api_key", "KE-test"),
        patch(
            "app.services.telephony.telnyx_voice.TelnyxVoiceService",
            return_value=fake_service,
        ),
        patch("asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
        await _delayed_hangup(
            call_control_id="ccid-xyz",
            delay_seconds=7.0,
            log=tool_executor_module.logger,
        )

    sleep_mock.assert_awaited_once_with(7.0)
    fake_service.hangup_call.assert_awaited_once_with("ccid-xyz")
    fake_service.close.assert_awaited_once()
