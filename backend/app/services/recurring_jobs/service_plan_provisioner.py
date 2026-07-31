"""Turn an approved quote into the Service Plans the client just signed up for.

Approval is the "signed up" moment. Until now a Care Plan existed only as a tier
key buried in ``quote.proposal_document``, and a Christmas signup produced no
recurring work at all — nothing recorded that *this client is on Gold* or that
someone has to hang their lights every November. This module writes that record.

Two signups are recognized, both read from the frozen proposal snapshot so a
later pricing-config edit can never retroactively change what a client bought:

* **Care Plan** — ``care_plan.selected`` names the tier the client picked. Its
  ``visits`` per year become the plan's recurrence, and the first visit lands one
  full period after signup (the install happens first; maintenance follows).
* **Christmas lights** — a ``christmas`` category section means a seasonal
  signup, which becomes **two** plans: install and takedown. They are genuinely
  different dispatchable jobs (different crew, duration, and checklist), so
  modelling them as one plan with a second cursor would fork the worker's
  exactly-once materialization for no operator benefit. Both plans are anchored
  on the workspace's configured season dates.

  The takedown plan is provisioned only when the client actually **bought**
  takedown (``ProposalCategorySection.takedown``). Dispatching a crew every
  January for work nobody paid for is recurring unpaid labour, and it recurs
  yearly. Sections written before that field existed record ``None``, which is
  read as "unknown" and provisions the takedown plan exactly as before — a
  season already sold never loses its crew.

Provisioning runs **inside the approval transaction**: a silently missing plan is
lost recurring revenue, so it is data, not a best-effort side effect. It is also
idempotent — re-approving a quote (an operator retry, a client double-clicking
the public approve button) is a no-op, guarded authoritatively by the partial
unique index on ``(source_quote_id, plan_type, title)`` rather than by the
pre-check alone.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quote import Quote
from app.models.recurring_job import (
    RecurrenceFrequency,
    RecurringJobTemplate,
    ServicePlanType,
)
from app.models.workspace import Workspace
from app.schemas.pricing import ChristmasConfig
from app.services.recurring_jobs.recurring_job_service import advance_occurrence

logger = structlog.get_logger()

# Generated jobs start mid-morning in US business hours; dispatch moves them on
# the board once the worker materializes them, so this is only a sane anchor.
_START_HOUR_UTC = 15

# Placeholder job windows an operator can tune per plan. A seasonal install is a
# half-day crew visit; takedown and a care-plan visit are shorter.
_CHRISTMAS_INSTALL_MINUTES = 240
_CHRISTMAS_TAKEDOWN_MINUTES = 120
_CARE_PLAN_VISIT_MINUTES = 90

# Seasonal work needs to be on the board earlier than routine maintenance so
# crews and materials can be staged before the season starts.
_CHRISTMAS_LEAD_DAYS = 30
_CARE_PLAN_LEAD_DAYS = 14


def _as_dict(value: Any) -> dict[str, Any]:
    """Read a JSONB sub-object defensively (a hand-edited blob never 500s)."""
    return value if isinstance(value, dict) else {}


def _sold(section: dict[str, Any], service: str) -> bool:
    """Whether an optional seasonal service was bought on this quote.

    Missing or non-boolean means *unknown*, not *declined*: sections written
    before the flag existed carry no value, and those quotes were provisioned
    with takedown. Defaulting to ``True`` keeps every already-sold season
    dispatching exactly as it does today; only quotes built after this shipped
    can turn a service off.
    """
    value = section.get(service)
    return value if isinstance(value, bool) else True


def _anchor_in_year(year: int, month: int, day: int) -> datetime:
    """The season anchor within ``year``, clamped to a day that month has."""
    return datetime(year, month, min(day, monthrange(year, month)[1]), _START_HOUR_UTC, tzinfo=UTC)


def _next_anchor(after: datetime, month: int, day: int) -> datetime:
    """First occurrence of ``month``/``day`` at or after ``after``."""
    candidate = _anchor_in_year(after.year, month, day)
    if candidate < after:
        candidate = _anchor_in_year(after.year + 1, month, day)
    return candidate


def _care_plan_recurrence(visits: int) -> tuple[RecurrenceFrequency, int]:
    """Map a tier's visits-per-year onto the plan's frequency × interval.

    One visit a year is a yearly plan; anything more spaces evenly across the
    twelve months (4 visits → every 3 months, 12 → monthly).
    """
    if visits <= 1:
        return RecurrenceFrequency.YEARLY, 1
    return RecurrenceFrequency.MONTHLY, max(1, 12 // min(visits, 12))


class ServicePlanProvisioner:
    """Creates the Service Plans an approved quote's signup implies."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="service_plan_provisioner")

    async def provision_from_quote(
        self, quote: Quote, *, now: datetime | None = None
    ) -> list[RecurringJobTemplate]:
        """Create the plans this approved quote signed the client up for.

        Returns the plans actually created — empty when the quote carries no
        subscription (a flat install-only job) or when it was already
        provisioned. Never raises for missing/odd document data: a quote that
        cannot be read as a signup simply provisions nothing.
        """
        document = _as_dict(quote.proposal_document)
        if not document or quote.contact_id is None:
            return []

        specs: list[dict[str, Any]] = []
        moment = now or datetime.now(UTC)
        # Plans start from the signup, but never in the past: backfilling a quote
        # approved last year must schedule the *next* season, not materialize a
        # job dated last November onto the dispatch board.
        anchor = max(quote.approved_at or moment, moment)
        care_plan = self._care_plan_spec(document, anchor)
        if care_plan is not None:
            specs.append(care_plan)
        if self._has_christmas_section(document):
            christmas = await self._christmas_config(quote.workspace_id)
            specs.extend(self._christmas_specs(document, christmas, anchor))
        if not specs:
            return []

        existing = await self._existing_titles(quote.id)
        created: list[RecurringJobTemplate] = []
        for spec in specs:
            if (spec["plan_type"], spec["title"]) in existing:
                continue
            plan = await self._insert(quote, spec)
            if plan is not None:
                created.append(plan)

        if created:
            self.log.info(
                "service_plans_provisioned",
                quote_id=str(quote.id),
                workspace_id=str(quote.workspace_id),
                plans=[plan.title for plan in created],
            )
        return created

    # ------------------------------------------------------------------ #
    # Signup readers
    # ------------------------------------------------------------------ #
    def _care_plan_spec(self, document: dict[str, Any], anchor: datetime) -> dict[str, Any] | None:
        """Build the Care Plan spec from the client's selected tier, if any."""
        care_plan = _as_dict(document.get("care_plan"))
        selected = str(care_plan.get("selected") or "").strip()
        if not selected:
            return None

        options = [_as_dict(option) for option in care_plan.get("options") or []]
        chosen = next((o for o in options if str(o.get("key") or "") == selected), {})
        name = str(chosen.get("name") or "").strip() or selected.replace("_", " ").title()
        visits = chosen.get("visits")
        frequency, interval = _care_plan_recurrence(int(visits) if isinstance(visits, int) else 1)
        return {
            "plan_type": ServicePlanType.LIGHTING_CARE_PLAN,
            "care_plan_tier": selected[:64],
            "title": f"Care Plan — {name}"[:200],
            "description": (
                f"{name} care plan visit. Auto-created when the client approved their proposal."
            ),
            "frequency": frequency,
            "interval": interval,
            "duration_minutes": _CARE_PLAN_VISIT_MINUTES,
            "generate_days_ahead": _CARE_PLAN_LEAD_DAYS,
            # The install comes first; maintenance starts one period later.
            "next_run_at": advance_occurrence(anchor, frequency, interval),
        }

    @staticmethod
    def _has_christmas_section(document: dict[str, Any]) -> bool:
        """True when the quote actually sold a seasonal Christmas package."""
        sections = document.get("category_sections") or []
        return any(_as_dict(section).get("key") == "christmas" for section in sections)

    @staticmethod
    def _christmas_section(document: dict[str, Any]) -> dict[str, Any]:
        """The frozen christmas section of this quote (empty when absent)."""
        for section in document.get("category_sections") or []:
            data = _as_dict(section)
            if data.get("key") == "christmas":
                return data
        return {}

    @classmethod
    def _christmas_label(cls, document: dict[str, Any]) -> str:
        """The workspace's Christmas label as frozen on this quote."""
        label = str(cls._christmas_section(document).get("label") or "").strip()
        return label or "Christmas Lighting"

    def _christmas_specs(
        self,
        document: dict[str, Any],
        config: ChristmasConfig,
        anchor: datetime,
    ) -> list[dict[str, Any]]:
        """Build the yearly install (+ takedown, when sold) for a seasonal signup."""
        label = self._christmas_label(document)
        section = self._christmas_section(document)
        install_at = _next_anchor(anchor, config.season_install_month, config.season_install_day)
        specs = [
            {
                "plan_type": ServicePlanType.CHRISTMAS_LIGHTS,
                "care_plan_tier": None,
                "title": f"{label} — Install"[:200],
                "description": self._install_description(section),
                "frequency": RecurrenceFrequency.YEARLY,
                "interval": 1,
                "duration_minutes": _CHRISTMAS_INSTALL_MINUTES,
                "generate_days_ahead": _CHRISTMAS_LEAD_DAYS,
                "next_run_at": install_at,
            }
        ]
        if not _sold(section, "takedown"):
            return specs

        # Takedown belongs to the season we just installed, so it must fall after
        # that install — not on the anchor that already passed this year.
        takedown_at = _next_anchor(
            install_at + timedelta(days=1),
            config.season_takedown_month,
            config.season_takedown_day,
        )
        specs.append(
            {
                "plan_type": ServicePlanType.CHRISTMAS_LIGHTS,
                "care_plan_tier": None,
                "title": f"{label} — Takedown"[:200],
                "description": self._takedown_description(section),
                "frequency": RecurrenceFrequency.YEARLY,
                "interval": 1,
                "duration_minutes": _CHRISTMAS_TAKEDOWN_MINUTES,
                "generate_days_ahead": _CHRISTMAS_LEAD_DAYS,
                "next_run_at": takedown_at,
            }
        )
        return specs

    @staticmethod
    def _install_description(section: dict[str, Any]) -> str:
        """Install instructions, mentioning storage retrieval when it was sold."""
        base = "Seasonal install. Auto-created when the client signed up for the season."
        if _sold(section, "storage"):
            return f"{base} Client bought off-season storage — pull their decor before the visit."
        return base

    @staticmethod
    def _takedown_description(section: dict[str, Any]) -> str:
        """Takedown instructions, mentioning storage collection when it was sold."""
        base = "Post-season takedown. Auto-created when the client signed up for the season."
        if _sold(section, "storage"):
            return f"{base} Client bought off-season storage — bring bins and haul the decor back."
        return base

    async def _christmas_config(self, workspace_id: Any) -> ChristmasConfig:
        """Season anchors from the workspace's pricing config (defaults when unset)."""
        # Imported here, not at module scope: ``app.services.quotes`` eagerly
        # imports ``QuoteService``, which imports this provisioner, so a
        # top-level import would be a package cycle.
        from app.services.quotes.pricing_config import get_pricing_config

        workspace = await self.db.get(Workspace, workspace_id)
        if workspace is None:  # pragma: no cover - the quote's workspace always exists
            return ChristmasConfig()
        return get_pricing_config(workspace).christmas

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    async def _existing_titles(self, quote_id: Any) -> set[tuple[str, str]]:
        """``(plan_type, title)`` pairs already provisioned from this quote."""
        rows = (
            await self.db.execute(
                select(RecurringJobTemplate.plan_type, RecurringJobTemplate.title).where(
                    RecurringJobTemplate.source_quote_id == quote_id
                )
            )
        ).all()
        return {(str(plan_type), str(title)) for plan_type, title in rows}

    async def _insert(self, quote: Quote, spec: dict[str, Any]) -> RecurringJobTemplate | None:
        """Insert one plan; ``None`` when a concurrent approve already made it.

        The savepoint keeps a lost race from poisoning the approval transaction:
        the unique index — not the pre-check — is what guarantees a client is
        never signed up twice.
        """
        plan = RecurringJobTemplate(
            workspace_id=quote.workspace_id,
            contact_id=quote.contact_id,
            service_location_id=quote.service_location_id,
            source_quote_id=quote.id,
            plan_type=str(spec["plan_type"]),
            care_plan_tier=spec["care_plan_tier"],
            title=spec["title"],
            description=spec["description"],
            frequency=str(spec["frequency"]),
            interval=spec["interval"],
            duration_minutes=spec["duration_minutes"],
            generate_days_ahead=spec["generate_days_ahead"],
            next_run_at=spec["next_run_at"],
            is_active=True,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(plan)
                await self.db.flush()
        except IntegrityError:
            self.log.info(
                "service_plan_already_provisioned",
                quote_id=str(quote.id),
                title=spec["title"],
            )
            return None
        return plan
