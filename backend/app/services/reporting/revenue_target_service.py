"""Monthly revenue targets and the month-pace report they make possible.

Two responsibilities:

1. **CRUD over :class:`app.models.revenue_target.RevenueTarget`** — one row per
   calendar month, addressed by month rather than by id. Writes go through a
   Postgres ``INSERT ... ON CONFLICT DO UPDATE`` keyed on
   ``(workspace_id, period_month)``, so "set June" is idempotent and two
   concurrent saves cannot produce a duplicate or a lost update. A bulk variant
   sets a whole season in one statement, which is what seasonal trades actually
   need: $130K in June and $45K in January, not a flat monthly number.

2. **:meth:`RevenueTargetService.get_pace`** — the answer to "are we on track?".
   It pairs the month's target with the month's actuals and reports both the
   money view (sold to date, linear projection, gap) and the funnel view
   (actual vs required leads / estimates / sold).

The required counts come from *backsolving* the goal, the way a home-service
owner does it on a whiteboard::

    jobs = revenue_goal / target_avg_job_value
    estimates = jobs / (target_close_rate / 100)
    leads = estimates / (assumed_sat_rate / 100)

Every one of those divisors is optional or operator-supplied, so
:func:`backsolve_funnel` treats a missing **or** non-positive value as unknown
and returns ``None`` for that stage and everything downstream of it. A workspace
that never entered an average job value gets "we don't know", never a
``ZeroDivisionError`` and never a misleading ``0``.

Where the actuals come from — deliberately the same canonical sources used by
the dashboard and ROI reports, so every surface agrees:

- **sold / revenue** — approved quotes by approval time, plus legacy/manual
  closed-won opportunities that have no approved quote; quote-backed wins are
  suppressed so revenue is counted once.
- **estimates** — :class:`~app.models.quote.Quote` rows created in the month
  that left ``draft``, matching the "issued" rule in
  :mod:`app.services.reporting.sales_performance_service`.
- **leads** — :class:`~app.models.contact.Contact` rows created in the month,
  matching ``new_leads_30d`` in :mod:`app.services.contacts.query_service`.

The maths is a pure function over plain dataclasses
(:func:`assemble_pace`), mirroring
:func:`app.services.reporting.sales_performance_service.assemble_sales_performance`,
so every guard is unit-testable without a database.
"""

from __future__ import annotations

import uuid
from calendar import monthrange
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import apply_workspace_scope, select_workspace_owned
from app.models.contact import Contact
from app.models.quote import Quote
from app.models.revenue_target import UQ_WORKSPACE_MONTH, RevenueTarget
from app.schemas.revenue_target import (
    PaceStage,
    PaceStageName,
    RevenuePace,
    RevenueTargetBulkUpsert,
    RevenueTargetList,
    RevenueTargetResponse,
    RevenueTargetUpsert,
)
from app.services.exceptions import NotFoundError
from app.services.reporting.booked_revenue import get_booked_revenue_totals
from app.services.reporting.time_windows import (
    get_workspace_reporting_timezone,
    local_date_bounds_utc,
)

logger = structlog.get_logger()

# Reported currency. Single-currency like the dashboard's ``RevenueStats``; a
# multi-currency workspace would need the ``_require_single_currency`` treatment
# the money reports use.
CURRENCY = "USD"

# Quote status that never reached a customer, so it is not an estimate.
_DRAFT_STATUS = "draft"

# Columns a client can set; also the ``DO UPDATE SET`` list of the upsert.
_MUTABLE_COLUMNS = (
    "revenue_goal",
    "target_avg_job_value",
    "target_close_rate",
    "assumed_sat_rate",
    "target_leads",
    "estimate_capacity_per_month",
    "crew_capacity_hours_per_week",
    "backlog_alert_weeks",
)


# --------------------------------------------------------------------------- #
# Month arithmetic
# --------------------------------------------------------------------------- #
def normalize_month(value: date) -> date:
    """Snap any date to the first day of its month.

    The single place a month is turned into a storage key, so ``2026-06-14`` and
    ``2026-06-01`` can never address two different June rows.
    """
    return value.replace(day=1)


def month_bounds(value: date) -> tuple[date, date]:
    """Return ``(first_day, last_day)`` of ``value``'s calendar month."""
    first = normalize_month(value)
    return first, first.replace(day=monthrange(first.year, first.month)[1])


def days_elapsed_in_month(value: date, today: date) -> tuple[int, int]:
    """Return ``(days_elapsed, days_in_month)`` for ``value``'s month as of ``today``.

    Today counts as elapsed (a month is 1/30th done on the 1st, not 0/30ths), so
    the last day of the month yields ``days_elapsed == days_in_month`` and the
    projection collapses onto the actual. A month that has not started yet
    yields ``0``, which callers must treat as "cannot project".
    """
    first, last = month_bounds(value)
    days_in_month = last.day
    if today < first:
        return 0, days_in_month
    if today >= last:
        return days_in_month, days_in_month
    return today.day, days_in_month


# --------------------------------------------------------------------------- #
# Pure pace maths
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TargetAssumptions:
    """The goal side of the pace report, flattened off the ORM row.

    All-``None`` is a legitimate state (no target set for the month); consumers
    must render that as "no goal", not as a goal of zero.
    """

    revenue_goal: float | None = None
    target_avg_job_value: float | None = None
    target_close_rate: float | None = None
    assumed_sat_rate: float | None = None
    target_leads: int | None = None
    estimate_capacity_per_month: int | None = None

    @classmethod
    def from_model(cls, target: RevenueTarget) -> TargetAssumptions:
        """Flatten a stored target, coercing ``Numeric`` columns to ``float``."""
        return cls(
            revenue_goal=_as_float(target.revenue_goal),
            target_avg_job_value=_as_float(target.target_avg_job_value),
            target_close_rate=_as_float(target.target_close_rate),
            assumed_sat_rate=_as_float(target.assumed_sat_rate),
            target_leads=target.target_leads,
            estimate_capacity_per_month=target.estimate_capacity_per_month,
        )


@dataclass(frozen=True)
class MonthActuals:
    """What the workspace actually did in the month so far."""

    revenue_sold_to_date: float = 0.0
    leads: int = 0
    estimates: int = 0
    sold: int = 0


@dataclass(frozen=True)
class FunnelRequirement:
    """Whole-month stage counts implied by the goal. ``None`` means unknown."""

    leads: float | None
    estimates: float | None
    jobs: float | None


def _as_float(value: float | None) -> float | None:
    """Coerce a ``Numeric`` column (Decimal at runtime) to ``float``."""
    return None if value is None else float(value)


def _divisor(value: float | None) -> float | None:
    """Return ``value`` only when it is safe to divide by.

    The single guard behind every ratio in this module: ``None`` (never set) and
    ``<= 0`` (nonsense, or a row that bypassed the schema/check constraints) are
    both "unknown", so the caller reports nothing rather than dividing.
    """
    if value is None:
        return None
    numeric = float(value)
    return numeric if numeric > 0 else None


def backsolve_funnel(target: TargetAssumptions) -> FunnelRequirement:
    """Turn a revenue goal into the stage counts required to hit it.

    Each stage depends on the one below it, so a missing assumption truncates
    the chain rather than poisoning it: no average job value means jobs,
    estimates and leads are all unknown; a known job count with no close rate
    still reports jobs.

    ``target_leads`` is the one override — an owner who typed their own lead
    number gets that number back, even when the derived one is available.
    """
    goal = target.revenue_goal
    avg_job_value = _divisor(target.target_avg_job_value)
    jobs = goal / avg_job_value if goal is not None and avg_job_value else None

    close_rate = _divisor(target.target_close_rate)
    estimates = jobs / (close_rate / 100) if jobs is not None and close_rate else None

    sat_rate = _divisor(target.assumed_sat_rate)
    leads = estimates / (sat_rate / 100) if estimates is not None and sat_rate else None
    if target.target_leads is not None:
        leads = float(target.target_leads)

    return FunnelRequirement(leads=leads, estimates=estimates, jobs=jobs)


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _stage(
    name: PaceStageName,
    actual: int,
    required: float | None,
    *,
    elapsed_share: float,
) -> PaceStage:
    """Build one funnel row, pro-rating the requirement to the month elapsed."""
    return PaceStage(
        stage=name,
        actual=actual,
        required=_round(required),
        required_to_date=_round(None if required is None else required * elapsed_share),
        gap=_round(None if required is None else required - actual),
    )


def assemble_pace(
    target: TargetAssumptions,
    actuals: MonthActuals,
    *,
    period_month: date,
    today: date,
    has_target: bool,
) -> RevenuePace:
    """Build the pace report from a target and the month's actuals (pure).

    Projection is linear in elapsed days. On the first of the month one sale
    projects to a whole month of sales — that is the honest reading of "at this
    rate", and the response carries ``days_elapsed`` so a client can say how
    little the projection is worth yet.
    """
    first, _ = month_bounds(period_month)
    days_elapsed, days_in_month = days_elapsed_in_month(first, today)
    elapsed_share = days_elapsed / days_in_month if days_in_month else 0.0

    goal = target.revenue_goal
    sold = round(actuals.revenue_sold_to_date, 2)
    # No elapsed days means nothing to extrapolate from; a future month projects
    # nothing rather than projecting zero.
    projected = round(sold / days_elapsed * days_in_month, 2) if days_elapsed else None

    required = backsolve_funnel(target)
    capacity = target.estimate_capacity_per_month
    over_capacity = (
        required.estimates - capacity
        if required.estimates is not None and capacity is not None
        else None
    )

    return RevenuePace(
        period_month=first,
        as_of=today,
        has_target=has_target,
        currency=CURRENCY,
        revenue_goal=_round(goal),
        revenue_sold_to_date=sold,
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
        projected_month_end=projected,
        gap_to_goal=_round(None if goal is None else goal - sold),
        projected_gap_to_goal=(
            _round(None if goal is None or projected is None else goal - projected)
        ),
        on_pace=None if goal is None or projected is None else projected >= goal,
        stages=[
            _stage("leads", actuals.leads, required.leads, elapsed_share=elapsed_share),
            _stage("estimates", actuals.estimates, required.estimates, elapsed_share=elapsed_share),
            _stage("sold", actuals.sold, required.jobs, elapsed_share=elapsed_share),
        ],
        estimate_capacity_per_month=capacity,
        estimates_over_capacity=_round(over_capacity),
    )


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
class RevenueTargetService:
    """Workspace-scoped monthly revenue targets and the month-pace report."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="revenue_target_service")

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    async def list_targets(
        self, workspace_id: uuid.UUID, *, year: int | None = None
    ) -> RevenueTargetList:
        """List a workspace's targets, oldest month first.

        ``year`` narrows to a single calendar year — the natural unit for the
        seasonal planning screen.
        """
        criteria = []
        if year is not None:
            criteria.append(RevenueTarget.period_month >= date(year, 1, 1))
            criteria.append(RevenueTarget.period_month <= date(year, 12, 1))

        rows = (
            (
                await self.db.execute(
                    select_workspace_owned(RevenueTarget, workspace_id, *criteria).order_by(
                        RevenueTarget.period_month.asc()
                    )
                )
            )
            .scalars()
            .all()
        )
        items = [RevenueTargetResponse.model_validate(row) for row in rows]
        return RevenueTargetList(items=items, total=len(items))

    async def get_target(
        self, workspace_id: uuid.UUID, period_month: date
    ) -> RevenueTargetResponse:
        """Fetch one month's target, or raise :class:`NotFoundError`."""
        target = await self._load_target(workspace_id, period_month)
        if target is None:
            raise NotFoundError(
                f"No revenue target set for {normalize_month(period_month).isoformat()[:7]}"
            )
        return RevenueTargetResponse.model_validate(target)

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    async def upsert_target(
        self, workspace_id: uuid.UUID, payload: RevenueTargetUpsert
    ) -> RevenueTargetResponse:
        """Set (or replace) one month's target."""
        saved = await self._upsert(workspace_id, [payload])
        return saved.items[0]

    async def bulk_upsert(
        self, workspace_id: uuid.UUID, payload: RevenueTargetBulkUpsert
    ) -> RevenueTargetList:
        """Set a season's worth of targets in one statement.

        All-or-nothing: one statement, one commit, so a rejected month never
        leaves half a year written.
        """
        return await self._upsert(workspace_id, payload.targets)

    async def delete_target(self, workspace_id: uuid.UUID, period_month: date) -> None:
        """Delete one month's target, or raise :class:`NotFoundError`."""
        target = await self._load_target(workspace_id, period_month)
        if target is None:
            raise NotFoundError(
                f"No revenue target set for {normalize_month(period_month).isoformat()[:7]}"
            )
        await self.db.delete(target)
        await self.db.commit()

    async def _upsert(
        self, workspace_id: uuid.UUID, targets: Sequence[RevenueTargetUpsert]
    ) -> RevenueTargetList:
        """Insert-or-update every month in ``targets`` atomically."""
        now = datetime.now(UTC)
        rows = [self._row_values(workspace_id, target, now=now) for target in targets]

        insert = pg_insert(RevenueTarget).values(rows)
        statement = insert.on_conflict_do_update(
            constraint=UQ_WORKSPACE_MONTH,
            set_={
                **{column: insert.excluded[column] for column in _MUTABLE_COLUMNS},
                "updated_at": insert.excluded.updated_at,
            },
        ).returning(RevenueTarget)

        saved = (await self.db.execute(statement)).scalars().all()
        await self.db.commit()
        self.log.info(
            "revenue_targets_upserted",
            workspace_id=str(workspace_id),
            months=[row["period_month"].isoformat() for row in rows],
        )

        items = sorted(
            (RevenueTargetResponse.model_validate(row) for row in saved),
            key=lambda item: item.period_month,
        )
        return RevenueTargetList(items=items, total=len(items))

    @staticmethod
    def _row_values(
        workspace_id: uuid.UUID, target: RevenueTargetUpsert, *, now: datetime
    ) -> dict[str, Any]:
        """Flatten one upsert payload into insert values.

        ``id`` and the timestamps are set explicitly rather than left to column
        defaults: a multi-row ``VALUES`` clause must name the same columns for
        every row, and the ``DO UPDATE`` branch needs ``updated_at`` in
        ``excluded`` to bump it (SQLAlchemy's Python-side ``onupdate`` never
        fires for an ``ON CONFLICT`` update).
        """
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "workspace_id": workspace_id,
            "period_month": normalize_month(target.period_month),
            "created_at": now,
            "updated_at": now,
        }
        values.update({column: getattr(target, column) for column in _MUTABLE_COLUMNS})
        return values

    # ------------------------------------------------------------------ #
    # Pace
    # ------------------------------------------------------------------ #
    async def get_pace(
        self,
        workspace_id: uuid.UUID,
        period_month: date | None = None,
        *,
        today: date | None = None,
    ) -> RevenuePace:
        """Report whether ``period_month`` is on pace to hit its revenue goal.

        Defaults to the current calendar month. A month with no stored target
        still reports its actuals with ``has_target: false``, so the dashboard
        can prompt "set a goal" instead of rendering an error.
        """
        timezone_name = await get_workspace_reporting_timezone(self.db, workspace_id)
        as_of = today or datetime.now(ZoneInfo(timezone_name)).date()
        month = normalize_month(period_month or as_of)

        target = await self._load_target(workspace_id, month)
        assumptions = (
            TargetAssumptions.from_model(target) if target is not None else TargetAssumptions()
        )
        actuals = await self._load_actuals(workspace_id, month, as_of, timezone_name=timezone_name)
        return assemble_pace(
            assumptions,
            actuals,
            period_month=month,
            today=as_of,
            has_target=target is not None,
        )

    async def _load_target(
        self, workspace_id: uuid.UUID, period_month: date
    ) -> RevenueTarget | None:
        """Load one month's target row, or ``None``."""
        result = await self.db.execute(
            select_workspace_owned(
                RevenueTarget,
                workspace_id,
                RevenueTarget.period_month == normalize_month(period_month),
            )
        )
        return result.scalar_one_or_none()

    async def _load_actuals(
        self,
        workspace_id: uuid.UUID,
        period_month: date,
        as_of: date,
        *,
        timezone_name: str,
    ) -> MonthActuals:
        """Count the month's leads, estimates and booked work up to ``as_of``."""
        first, last = month_bounds(period_month)
        if as_of < first:
            # The month has not started; nothing can have happened in it yet.
            return MonthActuals()
        through = min(as_of, last)

        # Half-open workspace-local window converted to UTC for timestamptz rows.
        start, end = local_date_bounds_utc(first, through, timezone_name)
        booked = await get_booked_revenue_totals(
            self.db,
            workspace_id,
            first,
            through,
            timezone_name=timezone_name,
        )

        leads = (
            await self.db.execute(
                apply_workspace_scope(select(func.count()), Contact, workspace_id).where(
                    Contact.created_at >= start, Contact.created_at < end
                )
            )
        ).scalar_one()

        estimates = (
            await self.db.execute(
                apply_workspace_scope(select(func.count()), Quote, workspace_id).where(
                    Quote.status != _DRAFT_STATUS,
                    Quote.created_at >= start,
                    Quote.created_at < end,
                )
            )
        ).scalar_one()

        return MonthActuals(
            revenue_sold_to_date=float(booked.revenue),
            leads=int(leads or 0),
            estimates=int(estimates or 0),
            sold=booked.count,
        )
