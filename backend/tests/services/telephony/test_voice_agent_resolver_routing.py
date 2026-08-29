"""Tests for reason-based routing in ``VoiceAgentResolver``.

Pins the routing contract added for inbound calls:

- A classified reason that maps to a valid agent in
  ``workspace.settings["call_routing"]`` wins over the default order.
- An unmapped or invalid reason falls back to the normal priority order.
- The keyword classifier maps free text to canonical reasons.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.telephony.inbound_routing import classify_reason_from_text
from app.services.telephony.voice_agent_resolver import VoiceAgentResolver


class _Result:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


def _make_agent(*, active: bool = True, channel_mode: str = "voice") -> MagicMock:
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.is_active = active
    agent.channel_mode = channel_mode
    agent.name = "Billing Bot"
    return agent


def _make_db(workspace: Any, execute_returns: list[Any]) -> MagicMock:
    db = MagicMock()
    db.get = AsyncMock(return_value=workspace)
    db.execute = AsyncMock(side_effect=list(execute_returns))
    return db


def _make_log() -> MagicMock:
    log = MagicMock()
    log.bind = MagicMock(return_value=log)
    return log


async def test_reason_routes_to_mapped_agent() -> None:
    workspace_id = uuid.uuid4()
    billing_agent = _make_agent()

    workspace = MagicMock()
    workspace.settings = {"call_routing": {"billing": str(billing_agent.id)}}

    conversation = MagicMock()
    conversation.id = uuid.uuid4()
    conversation.workspace_id = workspace_id
    conversation.assigned_agent_id = None

    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id
    phone_record.assigned_agent_id = None

    # Single execute: the _check_agent lookup for the routed agent.
    db = _make_db(workspace, execute_returns=[_Result(scalar=billing_agent)])

    resolver = VoiceAgentResolver()
    resolved = await resolver.resolve(db, conversation, phone_record, _make_log(), reason="billing")

    assert resolved is not None
    assert resolved.agent.id == billing_agent.id
    assert resolved.source == "reason_routing:billing"
    assert resolved.reason == "billing"


async def test_unmapped_reason_falls_back_to_phone_agent() -> None:
    workspace_id = uuid.uuid4()
    phone_agent = _make_agent()

    workspace = MagicMock()
    workspace.settings = {"call_routing": {"sales": str(uuid.uuid4())}}

    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id
    phone_record.assigned_agent_id = phone_agent.id

    # No conversation → reason routing misses (no "billing" route), campaign and
    # conversation-agent paths are skipped, phone-number agent is used.
    db = _make_db(workspace, execute_returns=[_Result(scalar=phone_agent)])

    resolver = VoiceAgentResolver()
    resolved = await resolver.resolve(db, None, phone_record, _make_log(), reason="billing")

    assert resolved is not None
    assert resolved.agent.id == phone_agent.id
    assert resolved.source == "phone_number_agent"
    assert resolved.reason is None


async def test_invalid_routed_agent_falls_back() -> None:
    workspace_id = uuid.uuid4()
    inactive_agent = _make_agent(active=False)
    phone_agent = _make_agent()

    workspace = MagicMock()
    workspace.settings = {"call_routing": {"billing": str(inactive_agent.id)}}

    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id
    phone_record.assigned_agent_id = phone_agent.id

    # 1st execute: routed (inactive) agent lookup → invalid → fall back.
    # 2nd execute: phone-number agent lookup → valid.
    db = _make_db(
        workspace,
        execute_returns=[_Result(scalar=inactive_agent), _Result(scalar=phone_agent)],
    )

    resolver = VoiceAgentResolver()
    resolved = await resolver.resolve(db, None, phone_record, _make_log(), reason="billing")

    assert resolved is not None
    assert resolved.agent.id == phone_agent.id
    assert resolved.source == "phone_number_agent"


async def test_no_reason_skips_routing() -> None:
    """Without a reason, routing is not attempted (no workspace lookup)."""
    workspace_id = uuid.uuid4()
    phone_agent = _make_agent()

    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id
    phone_record.assigned_agent_id = phone_agent.id

    db = _make_db(workspace=None, execute_returns=[_Result(scalar=phone_agent)])

    resolver = VoiceAgentResolver()
    resolved = await resolver.resolve(db, None, phone_record, _make_log())

    assert resolved is not None
    assert resolved.source == "phone_number_agent"
    db.get.assert_not_called()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I have a question about my invoice", "billing"),
        ("my app is broken and not working", "support"),
        ("I want to know your pricing for a demo", "sales"),
        ("just calling to say hi", None),
        ("", None),
        (None, None),
    ],
)
def test_classify_reason_from_text(text: str | None, expected: str | None) -> None:
    assert classify_reason_from_text(text) == expected


async def test_agent_lookup_is_scoped_to_the_phone_workspace() -> None:
    workspace_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result(scalar=None))

    resolved = await VoiceAgentResolver()._check_agent(
        db,
        uuid.uuid4(),
        workspace_id,
        "phone_number",
        _make_log(),
    )

    assert resolved is None
    statement = db.execute.await_args.args[0]
    assert "agents.workspace_id" in str(statement)
    assert workspace_id in statement.compile().params.values()
