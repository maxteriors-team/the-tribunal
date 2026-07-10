"""Staff assignment strategies for appointment booking.

Decides which bookable staff member an AI-driven booking should land on.
Booking is local (CRM-backed); any active staff member is eligible. Two
strategies are supported on top of the default single-assignee behavior:

- ``round_robin``: distribute bookings evenly across the agent's active staff
  pool, preferring whoever has the fewest assignments (ties broken by who was
  assigned least recently, then by priority).
- ``skill_based``: filter the pool to staff who have the requested skill, then
  round-robin among those matches.

The pure selection helpers (:func:`filter_staff_by_skill`,
:func:`pick_round_robin`, :func:`select_staff_member`) operate on plain lists of
staff-like objects so they can be unit-tested without a database. The async
:func:`resolve_staff_for_booking` wires them to the ORM, loads the agent's
active pool, picks a member, and records the round-robin counters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookable_staff import BookableStaff

if TYPE_CHECKING:
    from app.models.agent import Agent

logger = structlog.get_logger()

# Assignment strategy identifiers (mirror Agent.assignment_strategy).
STRATEGY_SINGLE = "single"
STRATEGY_ROUND_ROBIN = "round_robin"
STRATEGY_SKILL_BASED = "skill_based"
VALID_STRATEGIES = frozenset({STRATEGY_SINGLE, STRATEGY_ROUND_ROBIN, STRATEGY_SKILL_BASED})


class StaffLike(Protocol):
    """Minimal shape the selection helpers depend on.

    Lets the pure helpers be tested with lightweight stand-ins while also
    accepting real :class:`BookableStaff` ORM rows.
    """

    skills: list[str]
    is_active: bool
    priority: int
    assignment_count: int
    last_assigned_at: datetime | None
    calcom_event_type_id: int | None
    name: str


def _normalize(value: str | None) -> str:
    return (value or "").strip().casefold()


def filter_staff_by_skill[T: StaffLike](staff: list[T], skill: str | None) -> list[T]:
    """Return staff whose ``skills`` include ``skill`` (case-insensitive).

    When ``skill`` is falsy the full list is returned unchanged so callers can
    treat "no skill requested" as "any staff is eligible".
    """
    wanted = _normalize(skill)
    if not wanted:
        return list(staff)
    return [s for s in staff if any(_normalize(tag) == wanted for tag in (s.skills or []))]


def pick_round_robin[T: StaffLike](staff: list[T]) -> T | None:
    """Pick the next staff member for round-robin distribution.

    Selection order: fewest ``assignment_count`` first, then least recently
    assigned (``last_assigned_at`` ascending, never-assigned first), then highest
    ``priority``, then name for a stable deterministic tie-break.
    """
    eligible = [s for s in staff if s.is_active]
    if not eligible:
        return None

    # ``datetime.min`` (made tz-aware) sorts never-assigned staff first.
    epoch = datetime.min.replace(tzinfo=UTC)

    def sort_key(s: T) -> tuple[int, datetime, int, str]:
        last = s.last_assigned_at or epoch
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (s.assignment_count or 0, last, -(s.priority or 0), s.name or "")

    return min(eligible, key=sort_key)


def select_staff_member[T: StaffLike](
    staff: list[T],
    strategy: str,
    required_skill: str | None = None,
) -> T | None:
    """Pick a staff member per ``strategy``, or ``None`` to use the agent default.

    - ``single`` always returns ``None`` (legacy single-event-type behavior).
    - ``skill_based`` filters by ``required_skill`` first, then round-robins.
      If a skill was requested but nobody matches, returns ``None`` so the
      caller can fall back rather than booking the wrong specialist.
    - ``round_robin`` round-robins across the whole active pool.
    """
    if strategy == STRATEGY_SINGLE:
        return None

    candidates = [s for s in staff if s.is_active]

    if strategy == STRATEGY_SKILL_BASED:
        matched = filter_staff_by_skill(candidates, required_skill)
        if required_skill and not matched:
            # Requested a specific skill but no one has it — let caller fall back.
            return None
        candidates = matched

    return pick_round_robin(candidates)


async def resolve_staff_for_booking(
    db: AsyncSession,
    *,
    agent: Agent,
    required_skill: str | None = None,
    commit: bool = True,
    record: bool = True,
) -> BookableStaff | None:
    """Resolve and (optionally) record the staff member for a booking.

    Returns ``None`` when the agent uses the ``single`` strategy, has no
    eligible staff, or no staff matches a requested skill — in which case the
    caller should fall back to ``agent.calcom_event_type_id``.

    When ``record`` is True (the default, used for an actual booking) the
    chosen member's round-robin counters are bumped (``assignment_count`` +1,
    ``last_assigned_at`` = now) and persisted. Pass ``record=False`` to *peek*
    the selection — e.g. an availability check that needs the staff member's
    event type but must not consume a round-robin turn. The deterministic
    tie-break keeps a peek and the following booking on the same member as long
    as no other booking lands in between.
    """
    strategy = getattr(agent, "assignment_strategy", STRATEGY_SINGLE) or STRATEGY_SINGLE
    if strategy not in VALID_STRATEGIES or strategy == STRATEGY_SINGLE:
        return None

    result = await db.execute(
        select(BookableStaff).where(
            BookableStaff.agent_id == agent.id,
            BookableStaff.is_active.is_(True),
        )
    )
    pool = list(result.scalars().all())
    if not pool:
        logger.info(
            "staff_assignment_empty_pool",
            agent_id=str(agent.id),
            strategy=strategy,
        )
        return None

    chosen = select_staff_member(pool, strategy, required_skill)
    if chosen is None:
        logger.info(
            "staff_assignment_no_match",
            agent_id=str(agent.id),
            strategy=strategy,
            required_skill=required_skill,
            pool_size=len(pool),
        )
        return None

    if not record:
        # Peek only — don't consume a round-robin turn (e.g. availability check).
        return chosen

    chosen.assignment_count = (chosen.assignment_count or 0) + 1
    chosen.last_assigned_at = datetime.now(UTC)
    db.add(chosen)
    if commit:
        await db.commit()
        await db.refresh(chosen)
    else:
        await db.flush()

    logger.info(
        "staff_assigned",
        agent_id=str(agent.id),
        strategy=strategy,
        required_skill=required_skill,
        staff_id=str(chosen.id),
        staff_name=chosen.name,
        calcom_event_type_id=chosen.calcom_event_type_id,
        assignment_count=chosen.assignment_count,
    )
    return chosen


def staff_to_assignment_dict(staff: BookableStaff) -> dict[str, object]:
    """Compact dict describing an assigned staff member for tool/result payloads."""
    return {
        "id": str(staff.id),
        "name": staff.name,
        "calcom_event_type_id": staff.calcom_event_type_id,
        "skills": list(staff.skills or []),
    }


__all__ = [
    "STRATEGY_ROUND_ROBIN",
    "STRATEGY_SINGLE",
    "STRATEGY_SKILL_BASED",
    "VALID_STRATEGIES",
    "filter_staff_by_skill",
    "pick_round_robin",
    "resolve_staff_for_booking",
    "select_staff_member",
    "staff_to_assignment_dict",
]
