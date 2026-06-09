"""Tests for multi-staff round-robin and skill-based appointment assignment.

Covers the pure selection helpers (skill filtering, round-robin tie-breaking,
strategy dispatch) and the DB-backed ``resolve_staff_for_booking`` resolver,
including even distribution across the pool over many bookings.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.calendar.staff_assignment import (
    STRATEGY_ROUND_ROBIN,
    STRATEGY_SINGLE,
    STRATEGY_SKILL_BASED,
    filter_staff_by_skill,
    pick_round_robin,
    resolve_staff_for_booking,
    select_staff_member,
)


@dataclass
class FakeStaff:
    """Lightweight stand-in matching the StaffLike protocol."""

    name: str
    calcom_event_type_id: int | None = 100
    skills: list[str] = field(default_factory=list)
    is_active: bool = True
    priority: int = 0
    assignment_count: int = 0
    last_assigned_at: datetime | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


# ── Skill filtering ──────────────────────────────────────────────────


def test_filter_by_skill_matches_case_insensitively() -> None:
    staff = [
        FakeStaff("Alice", skills=["Spanish", "Mortgage"]),
        FakeStaff("Bob", skills=["english"]),
        FakeStaff("Cleo", skills=["SPANISH"]),
    ]
    matched = filter_staff_by_skill(staff, "spanish")
    assert {s.name for s in matched} == {"Alice", "Cleo"}


def test_filter_by_skill_none_returns_all() -> None:
    staff = [FakeStaff("Alice", skills=["x"]), FakeStaff("Bob", skills=[])]
    assert filter_staff_by_skill(staff, None) == staff
    assert filter_staff_by_skill(staff, "  ") == staff


def test_filter_by_skill_no_match_is_empty() -> None:
    staff = [FakeStaff("Alice", skills=["spanish"])]
    assert filter_staff_by_skill(staff, "german") == []


# ── Round-robin selection ────────────────────────────────────────────


def test_pick_round_robin_prefers_fewest_assignments() -> None:
    staff = [
        FakeStaff("Alice", assignment_count=5),
        FakeStaff("Bob", assignment_count=2),
        FakeStaff("Cleo", assignment_count=9),
    ]
    assert pick_round_robin(staff).name == "Bob"


def test_pick_round_robin_breaks_ties_by_last_assigned() -> None:
    now = datetime.now(UTC)
    staff = [
        FakeStaff("Alice", assignment_count=3, last_assigned_at=now),
        FakeStaff("Bob", assignment_count=3, last_assigned_at=now - timedelta(hours=1)),
    ]
    # Same count -> least recently assigned wins.
    assert pick_round_robin(staff).name == "Bob"


def test_pick_round_robin_never_assigned_first() -> None:
    now = datetime.now(UTC)
    staff = [
        FakeStaff("Alice", assignment_count=0, last_assigned_at=now),
        FakeStaff("Bob", assignment_count=0, last_assigned_at=None),
    ]
    assert pick_round_robin(staff).name == "Bob"


def test_pick_round_robin_priority_tiebreak() -> None:
    staff = [
        FakeStaff("Alice", assignment_count=0, priority=1),
        FakeStaff("Bob", assignment_count=0, priority=5),
    ]
    assert pick_round_robin(staff).name == "Bob"


def test_pick_round_robin_skips_inactive_and_no_event_type() -> None:
    staff = [
        FakeStaff("Inactive", is_active=False, assignment_count=0),
        FakeStaff("NoEvent", calcom_event_type_id=None, assignment_count=0),
        FakeStaff("Valid", assignment_count=4),
    ]
    assert pick_round_robin(staff).name == "Valid"


def test_pick_round_robin_empty_returns_none() -> None:
    assert pick_round_robin([]) is None
    assert pick_round_robin([FakeStaff("X", is_active=False)]) is None


def test_round_robin_distributes_evenly_over_many_bookings() -> None:
    """Simulating the resolver's count bump yields near-even distribution."""
    staff = [FakeStaff("A"), FakeStaff("B"), FakeStaff("C")]
    counts: Counter[str] = Counter()
    for _ in range(30):
        chosen = pick_round_robin(staff)
        assert chosen is not None
        chosen.assignment_count += 1
        chosen.last_assigned_at = datetime.now(UTC)
        counts[chosen.name] += 1
    # 30 bookings across 3 staff -> exactly 10 each.
    assert counts["A"] == counts["B"] == counts["C"] == 10


# ── Strategy dispatch ────────────────────────────────────────────────


def test_select_single_strategy_always_none() -> None:
    staff = [FakeStaff("Alice")]
    assert select_staff_member(staff, STRATEGY_SINGLE) is None


def test_select_round_robin_picks_least_loaded() -> None:
    staff = [FakeStaff("Alice", assignment_count=2), FakeStaff("Bob", assignment_count=0)]
    chosen = select_staff_member(staff, STRATEGY_ROUND_ROBIN)
    assert chosen is not None and chosen.name == "Bob"


def test_select_skill_based_filters_then_round_robins() -> None:
    staff = [
        FakeStaff("Alice", skills=["spanish"], assignment_count=5),
        FakeStaff("Bob", skills=["spanish"], assignment_count=1),
        FakeStaff("Cleo", skills=["german"], assignment_count=0),
    ]
    chosen = select_staff_member(staff, STRATEGY_SKILL_BASED, required_skill="spanish")
    # Cleo has fewest assignments but lacks the skill; Bob wins among matches.
    assert chosen is not None and chosen.name == "Bob"


def test_select_skill_based_no_match_returns_none() -> None:
    staff = [FakeStaff("Alice", skills=["spanish"])]
    assert select_staff_member(staff, STRATEGY_SKILL_BASED, required_skill="german") is None


def test_select_skill_based_no_skill_uses_whole_pool() -> None:
    staff = [
        FakeStaff("Alice", skills=["spanish"], assignment_count=3),
        FakeStaff("Bob", skills=[], assignment_count=0),
    ]
    chosen = select_staff_member(staff, STRATEGY_SKILL_BASED, required_skill=None)
    assert chosen is not None and chosen.name == "Bob"


# ── DB-backed resolver ───────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    """Minimal async session returning a fixed staff pool from execute()."""

    def __init__(self, pool: list[Any]) -> None:
        self._pool = pool
        self.committed = False

    async def execute(self, _query: Any) -> _FakeResult:
        return _FakeResult(self._pool)

    def add(self, _obj: Any) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


def _agent(strategy: str) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), assignment_strategy=strategy, calcom_event_type_id=1)


@pytest.mark.asyncio
async def test_resolve_single_strategy_skips_query() -> None:
    session = _FakeSession([FakeStaff("Alice")])
    chosen = await resolve_staff_for_booking(session, agent=_agent(STRATEGY_SINGLE))
    assert chosen is None
    assert session.committed is False


@pytest.mark.asyncio
async def test_resolve_round_robin_bumps_counters() -> None:
    pool = [FakeStaff("Alice", assignment_count=0), FakeStaff("Bob", assignment_count=2)]
    session = _FakeSession(pool)
    chosen = await resolve_staff_for_booking(session, agent=_agent(STRATEGY_ROUND_ROBIN))
    assert chosen is not None and chosen.name == "Alice"
    assert chosen.assignment_count == 1
    assert chosen.last_assigned_at is not None
    assert session.committed is True


@pytest.mark.asyncio
async def test_resolve_skill_based_matches() -> None:
    pool = [
        FakeStaff("Alice", skills=["mortgage"]),
        FakeStaff("Bob", skills=["spanish"]),
    ]
    session = _FakeSession(pool)
    chosen = await resolve_staff_for_booking(
        session, agent=_agent(STRATEGY_SKILL_BASED), required_skill="spanish"
    )
    assert chosen is not None and chosen.name == "Bob"


@pytest.mark.asyncio
async def test_resolve_skill_based_no_match_returns_none() -> None:
    pool = [FakeStaff("Alice", skills=["mortgage"])]
    session = _FakeSession(pool)
    chosen = await resolve_staff_for_booking(
        session, agent=_agent(STRATEGY_SKILL_BASED), required_skill="german"
    )
    assert chosen is None


@pytest.mark.asyncio
async def test_resolve_empty_pool_returns_none() -> None:
    session = _FakeSession([])
    chosen = await resolve_staff_for_booking(session, agent=_agent(STRATEGY_ROUND_ROBIN))
    assert chosen is None
