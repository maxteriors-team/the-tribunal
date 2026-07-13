"""Tests for capping the first AI reply's delay by the speed-to-lead SLA.

The human-like text response delay (22-30s+, scaling with reply length) must
never push the FIRST reply to a new lead past the workspace speed-to-lead SLA,
which is stamped at outbound-send time and drives the advertised proof badge.
Ongoing conversation keeps its full human-like pacing.
"""

from __future__ import annotations

import types
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services.ai.text_agent import _first_response_sla_cap_ms


class _FakeDB:
    def __init__(self, workspace: object | None) -> None:
        self._workspace = workspace

    async def get(self, _model: object, _id: object) -> object | None:
        return self._workspace


def _workspace(settings: dict[str, object] | None) -> types.SimpleNamespace:
    return types.SimpleNamespace(id=uuid.uuid4(), settings=settings)


def _conversation(
    first_inbound_at: datetime | None,
    first_response_at: datetime | None = None,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        workspace_id=uuid.uuid4(),
        first_inbound_at=first_inbound_at,
        first_response_at=first_response_at,
    )


async def test_cap_is_remaining_sla_budget_for_first_response() -> None:
    ws = _workspace({"speed_to_lead": {"enabled": True, "sla_seconds": 60}})
    conversation = _conversation(datetime.now(UTC) - timedelta(seconds=5))

    cap = await _first_response_sla_cap_ms(_FakeDB(ws), conversation)

    # 0.8 * 60_000 budget - ~5_000 elapsed.
    assert cap is not None
    assert 42_000 <= cap <= 44_000


async def test_late_first_response_caps_to_zero() -> None:
    ws = _workspace({"speed_to_lead": {"enabled": True, "sla_seconds": 60}})
    conversation = _conversation(datetime.now(UTC) - timedelta(seconds=55))

    cap = await _first_response_sla_cap_ms(_FakeDB(ws), conversation)

    assert cap == 0  # already past budget -> send immediately, never negative


async def test_ongoing_conversation_is_not_capped() -> None:
    ws = _workspace({"speed_to_lead": {"enabled": True, "sla_seconds": 60}})
    now = datetime.now(UTC)
    conversation = _conversation(now - timedelta(seconds=5), first_response_at=now)

    assert await _first_response_sla_cap_ms(_FakeDB(ws), conversation) is None


async def test_outbound_first_conversation_is_not_capped() -> None:
    ws = _workspace({"speed_to_lead": {"enabled": True, "sla_seconds": 60}})
    conversation = _conversation(first_inbound_at=None)

    assert await _first_response_sla_cap_ms(_FakeDB(ws), conversation) is None


async def test_speed_to_lead_disabled_is_not_capped() -> None:
    ws = _workspace({"speed_to_lead": {"enabled": False, "sla_seconds": 60}})
    conversation = _conversation(datetime.now(UTC) - timedelta(seconds=5))

    assert await _first_response_sla_cap_ms(_FakeDB(ws), conversation) is None


@pytest.mark.parametrize("sla_seconds", [10, 30, 120])
async def test_cap_scales_with_configured_sla(sla_seconds: int) -> None:
    ws = _workspace({"speed_to_lead": {"enabled": True, "sla_seconds": sla_seconds}})
    conversation = _conversation(datetime.now(UTC) - timedelta(seconds=1))

    cap = await _first_response_sla_cap_ms(_FakeDB(ws), conversation)

    expected = int(sla_seconds * 1000 * 0.8) - 1000
    assert cap is not None
    assert abs(cap - expected) <= 1500
