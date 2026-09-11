"""Inbound operator ringing: one winner, no silent callers, no cross-tenant rings.

The failure modes worth pinning are the ones a caller would feel: two operators
bridged onto one person, a headset that rings forever, or — worst — a customer
left in silence because the humans did not pick up and nothing took over.
"""

from __future__ import annotations

import fnmatch
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.telephony import inbound_operator_ring as ring
from app.services.telephony import operator_presence as presence

WORKSPACE_ID = uuid.uuid4()
OTHER_WORKSPACE_ID = uuid.uuid4()
MESSAGE_ID = uuid.uuid4()
CALLER_CCID = "v3:caller-leg"


class _FakeRedis:
    """Enough real Redis semantics for the parts this feature depends on."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def scan_iter(self, match: str, count: int = 100) -> AsyncIterator[str]:
        for key in list(self.store):
            if fnmatch.fnmatch(key, match):
                yield key


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    client = _FakeRedis()

    async def fake_get_redis() -> Any:
        return client

    monkeypatch.setattr(ring, "get_redis", fake_get_redis)
    monkeypatch.setattr(presence, "get_redis", fake_get_redis)

    # The winner path stamps the Message row; no database is needed to prove the
    # bridging and teardown decisions this module owns.
    session = MagicMock()
    session.get = AsyncMock(return_value=MagicMock())
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", MagicMock(return_value=session))
    return client


def _voice_service(dialed: list[str] | None = None) -> MagicMock:
    service = MagicMock()
    legs = iter(["v3:op-leg-1", "v3:op-leg-2", "v3:op-leg-3"] if dialed is None else dialed)
    service.dial_browser_leg = AsyncMock(side_effect=lambda **_: next(legs, None))
    service.bridge_calls = AsyncMock(return_value=True)
    service.hangup_call = AsyncMock(return_value=True)
    return service


def _db(rows: list[tuple[int, str]]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


async def _ring(db: MagicMock, service: MagicMock) -> bool:
    return await ring.ring_operators(
        db=db,
        voice_service=service,
        workspace_id=WORKSPACE_ID,
        message_id=MESSAGE_ID,
        caller_call_control_id=CALLER_CCID,
        from_number="+15551230000",
        connection_id="conn-1",
        webhook_url="https://example.com/webhooks/telnyx/voice",
        log=MagicMock(),
    )


async def test_rings_available_headsets_and_records_state(redis: _FakeRedis) -> None:
    await presence.mark_available(str(WORKSPACE_ID), 7)
    service = _voice_service()

    assert await _ring(_db([(7, "gencred-7")]), service) is True

    service.dial_browser_leg.assert_awaited_once()
    assert service.dial_browser_leg.await_args.kwargs["sip_username"] == "gencred-7"
    assert service.dial_browser_leg.await_args.kwargs["timeout_secs"] == ring.RING_TIMEOUT_SECONDS
    # State is readable from the caller leg *and* the operator leg, because the
    # accept webhook can land on either and on any replica.
    assert await ring.peek_pending_ring(CALLER_CCID) is not None
    assert await ring.peek_pending_ring("v3:op-leg-1") is not None


async def test_first_accept_wins_and_the_other_headsets_stop(redis: _FakeRedis) -> None:
    await presence.mark_available(str(WORKSPACE_ID), 7)
    await presence.mark_available(str(WORKSPACE_ID), 8)
    service = _voice_service()
    await _ring(_db([(7, "gencred-7"), (8, "gencred-8")]), service)

    winner = await ring.handle_operator_leg_answered("v3:op-leg-1", service, MagicMock())
    loser = await ring.handle_operator_leg_answered("v3:op-leg-2", service, MagicMock())

    assert winner is True and loser is True
    service.bridge_calls.assert_awaited_once_with(
        call_control_id="v3:op-leg-1",
        other_call_control_id=CALLER_CCID,
    )
    # The loser's headset is dropped; the caller leg is never touched.
    assert service.hangup_call.await_args_list[0].args == ("v3:op-leg-2",)
    assert all(call.args != (CALLER_CCID,) for call in service.hangup_call.await_args_list)
    assert await presence.is_busy(str(WORKSPACE_ID), 7) is True


async def test_unanswered_ring_hands_the_caller_back_to_the_normal_path(
    redis: _FakeRedis,
) -> None:
    """The caller is still holding, so the AI/fallback path must take over."""
    await presence.mark_available(str(WORKSPACE_ID), 7)
    service = _voice_service()
    await _ring(_db([(7, "gencred-7")]), service)

    outcome = await ring.handle_operator_leg_hangup("v3:op-leg-1", service, MagicMock())

    assert outcome == "exhausted"
    assert await presence.is_busy(str(WORKSPACE_ID), 7) is False


async def test_answered_call_ending_does_not_re_answer_with_ai(redis: _FakeRedis) -> None:
    await presence.mark_available(str(WORKSPACE_ID), 7)
    service = _voice_service()
    await _ring(_db([(7, "gencred-7")]), service)
    await ring.handle_operator_leg_answered("v3:op-leg-1", service, MagicMock())

    outcome = await ring.handle_operator_leg_hangup("v3:op-leg-1", service, MagicMock())

    assert outcome == "handled"


async def test_one_headset_left_ringing_keeps_the_ring_alive(redis: _FakeRedis) -> None:
    await presence.mark_available(str(WORKSPACE_ID), 7)
    await presence.mark_available(str(WORKSPACE_ID), 8)
    service = _voice_service()
    await _ring(_db([(7, "gencred-7"), (8, "gencred-8")]), service)

    outcome = await ring.handle_operator_leg_hangup("v3:op-leg-1", service, MagicMock())

    assert outcome == "handled"
    assert await ring.peek_pending_ring("v3:op-leg-2") is not None


async def test_caller_giving_up_stops_every_headset(redis: _FakeRedis) -> None:
    await presence.mark_available(str(WORKSPACE_ID), 7)
    await presence.mark_available(str(WORKSPACE_ID), 8)
    service = _voice_service()
    await _ring(_db([(7, "gencred-7"), (8, "gencred-8")]), service)

    outcome = await ring.handle_operator_leg_hangup(CALLER_CCID, service, MagicMock())

    assert outcome == "handled"
    hung_up = {call.args[0] for call in service.hangup_call.await_args_list}
    assert hung_up == {"v3:op-leg-1", "v3:op-leg-2"}
    assert await ring.peek_pending_ring("v3:op-leg-1") is None


async def test_busy_operator_is_not_rung_for_a_second_call(redis: _FakeRedis) -> None:
    await presence.mark_available(str(WORKSPACE_ID), 7)
    await presence.mark_busy(str(WORKSPACE_ID), 7)

    assert await presence.list_idle_available(str(WORKSPACE_ID)) == []


async def test_presence_never_leaks_across_workspaces(redis: _FakeRedis) -> None:
    await presence.mark_available(str(OTHER_WORKSPACE_ID), 99)

    assert await presence.list_available(str(WORKSPACE_ID)) == []
    assert await presence.list_available(str(OTHER_WORKSPACE_ID)) == [99]


async def test_no_available_operator_falls_through_without_dialing(redis: _FakeRedis) -> None:
    service = _voice_service()

    assert await _ring(_db([]), service) is False
    service.dial_browser_leg.assert_not_awaited()


async def test_operator_without_a_registered_headset_falls_through(redis: _FakeRedis) -> None:
    """Present in Redis, but no provisioned SIP identity to dial."""
    await presence.mark_available(str(WORKSPACE_ID), 7)
    service = _voice_service()

    assert await _ring(_db([]), service) is False
    service.dial_browser_leg.assert_not_awaited()


async def test_every_dial_failing_falls_through(redis: _FakeRedis) -> None:
    await presence.mark_available(str(WORKSPACE_ID), 7)
    service = _voice_service(dialed=[])

    assert await _ring(_db([(7, "gencred-7")]), service) is False
    assert await ring.peek_pending_ring(CALLER_CCID) is None


async def test_redis_failure_refuses_the_claim_rather_than_double_bridging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_redis() -> Any:
        raise RuntimeError("redis down")

    monkeypatch.setattr(ring, "get_redis", broken_redis)

    assert await ring.claim_call(CALLER_CCID, "v3:op-leg-1") is False
    # And an unknown claim state must not re-answer a finished call with AI.
    assert await ring.is_claimed(CALLER_CCID) is True


def test_client_state_marker_rejects_untrusted_values() -> None:
    assert ring.decode_operator_ring_client_state(
        ring.make_operator_ring_client_state(MESSAGE_ID)
    ) == str(MESSAGE_ID)
    assert ring.decode_operator_ring_client_state("not-base64") is None
    assert ring.decode_operator_ring_client_state("x" * 300) is None
    assert ring.decode_operator_ring_client_state(None) is None
