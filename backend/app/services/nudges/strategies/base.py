"""Base class and shared helpers for nudge generation strategies."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.human_nudge import HumanNudge


@dataclass
class NudgeContext:
    """Shared per-run state passed to each strategy.

    Holds parsed workspace settings and any data the orchestrator pre-fetches
    so individual strategies don't duplicate queries.
    """

    workspace_id: uuid.UUID
    lead_days: int
    cooling_days: int
    enabled_types: list[str]
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    date_contacts: list[Contact] = field(default_factory=list)

    @property
    def today(self) -> date:
        return self.now.date()

    @property
    def date_window_end(self) -> date:
        return self.today + timedelta(days=self.lead_days)


class NudgeStrategy(ABC):
    """Abstract base class for a single nudge-type generator.

    Strategies are stateless; all per-run data lives on the injected
    ``NudgeContext``. ``generate`` returns the count of newly created
    ``HumanNudge`` rows it added to the session.
    """

    nudge_type: str

    @abstractmethod
    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        """Create HumanNudge rows for this strategy's nudge type."""


async def dedup_exists(db: AsyncSession, dedup_key: str) -> bool:
    """Return True if a HumanNudge with ``dedup_key`` already exists."""
    result = await db.execute(
        select(HumanNudge.id).where(HumanNudge.dedup_key == dedup_key).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def load_contact(db: AsyncSession, contact_id: int) -> Contact | None:
    """Load a single Contact by id, or None."""
    result = await db.execute(select(Contact).where(Contact.id == contact_id).limit(1))
    return result.scalar_one_or_none()


def project_date_to_window(parsed: date, today: date) -> date:
    """Project a recurring date to its next upcoming occurrence."""
    this_year_date = parsed.replace(year=today.year)
    if this_year_date < today:
        this_year_date = parsed.replace(year=today.year + 1)
    return this_year_date


def parse_iso_date(date_str: str) -> date | None:
    """Parse a ``YYYY-MM-DD`` string, returning None on failure."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()  # noqa: DTZ007
    except (ValueError, TypeError):
        return None


def build_nudge_message(
    contact: Contact,
    nudge_type: str,
    date_str: str | None = None,
    days_until: int | None = None,
    label: str | None = None,
) -> tuple[str, str, str | None]:
    """Return (title, message, suggested_action) for a date/cooling nudge type."""
    first = contact.first_name
    last = contact.last_name or ""
    name = f"{first} {last}".strip()

    if nudge_type == "birthday":
        return (
            f"\U0001f382 {name}'s birthday coming up",
            f"\U0001f382 {name}'s birthday is in {days_until} days ({date_str}). "
            f"Consider sending a handwritten card!",
            "send_card",
        )
    if nudge_type == "anniversary":
        return (
            f"\U0001f48d {name}'s anniversary coming up",
            f"\U0001f48d {name}'s anniversary is in {days_until} days ({date_str}).",
            "send_card",
        )
    if nudge_type == "cooling":
        return (
            f"\U0001f504 Re-engage {name}",
            f"\U0001f504 Haven't heard from {name} in {days_until} days. Time to reach out?",
            "call",
        )
    event_label = label or "Event"
    return (
        f"\U0001f4c5 {event_label} for {name}",
        f"\U0001f4c5 {event_label} for {name} is in {days_until} days ({date_str}).",
        None,
    )


async def maybe_create_date_nudge(
    db: AsyncSession,
    context: NudgeContext,
    contact: Contact,
    nudge_type: str,
    date_str: str,
    label: str | None = None,
) -> int:
    """Create a date-based nudge if it falls within the lookahead window."""
    parsed = parse_iso_date(date_str)
    if parsed is None:
        return 0

    today = context.today
    this_year_date = project_date_to_window(parsed, today)

    if not (today <= this_year_date <= context.date_window_end):
        return 0

    days_until = (this_year_date - today).days
    dedup_suffix = label or nudge_type
    dedup_key = f"{contact.id}:{dedup_suffix}:{this_year_date.year}"

    if await dedup_exists(db, dedup_key):
        return 0

    title, message, suggested_action = build_nudge_message(
        contact,
        nudge_type,
        date_str=this_year_date.strftime("%B %d"),
        days_until=days_until,
        label=label,
    )

    nudge = HumanNudge(
        workspace_id=context.workspace_id,
        contact_id=contact.id,
        nudge_type=nudge_type,
        title=title,
        message=message,
        suggested_action=suggested_action,
        priority="high" if days_until <= 1 else "medium",
        due_date=datetime.combine(this_year_date, datetime.min.time(), tzinfo=UTC),
        source_date_field=label or nudge_type,
        status="pending",
        dedup_key=dedup_key,
    )
    db.add(nudge)
    return 1
