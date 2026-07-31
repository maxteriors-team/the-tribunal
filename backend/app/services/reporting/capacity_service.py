"""Backlog and estimate capacity — the workspace's fuel gauge.

Every other report here looks *backwards*: AR aging says who owes money, job P&L
says what past work earned, sales performance says how the quoting went. None of
them answer the one forward-looking question a home-service owner runs on:

    "How many weeks of work do I have booked?"

That number is the trigger for everything discretionary. Thin backlog means the
next dollar goes to marketing *now*, while there is still time for a lead to
become a job. Fat backlog means stop selling and start hiring. Without it a dry
spell arrives as a surprise in six weeks instead of a forecast today.

Two reports:

- :meth:`CapacityService.compute_backlog` — sold-but-not-yet-delivered work,
  divided by weekly crew capacity, expressed in weeks. **Delivery** capacity.
- :meth:`CapacityService.compute_estimate_capacity` — estimate appointments
  booked in a month against the number the workspace says it can run. **Sales**
  capacity, and the hire trigger: one full-time closer tops out near 60-80
  estimates a month, so sustained utilization above
  :data:`AT_CAPACITY_THRESHOLD_PCT` means the next dollar belongs in headcount,
  not in ads — more leads into a full calendar just makes the calendar later.

Where the numbers come from
---------------------------
**Backlog jobs** — :class:`~app.models.field_service.Job` rows in
:data:`OPEN_JOB_STATUSES`. ``completed`` work is delivered (not backlog) and
``cancelled`` work was never sold, so both are excluded; counting either would
report fuel that does not exist.

**Job hours** — the ``scheduled_start``/``scheduled_end`` window when the job has
one, else :data:`DEFAULT_JOB_HOURS` (overridable per call). ``Job`` carries no
duration column, so an unscheduled job — which by definition has no window — has
no measurable size, and refusing to estimate would make the report read as an
empty backlog exactly when the queue is deepest. The response therefore carries
``assumed_duration_job_count`` so a client can say how much of the number is
measured versus assumed.

This is also where **pre-booked** work lands. A paid pre-booking deposit creates
a provisional ``unscheduled`` job (see
:meth:`app.services.prebooking.reservation_service.PreBookingReservationService.confirm_reservation_for_quote`)
so next spring's sold work shows on the gauge in November, when the decision it
informs — spend on marketing, or hire — is still open. Those jobs deliberately
carry no window: stamping the whole target season on one would size a four-hour
house wash at ~2 200 hours and make this report worse than useless.

**Capacity** — :class:`~app.models.revenue_target.RevenueTarget`'s
``crew_capacity_hours_per_week`` and ``estimate_capacity_per_month``. Both are
nullable owner-entered planning fields, so both are treated as *unknown* when
missing or non-positive: every ratio here returns ``None`` rather than ``0``, and
never divides. A workspace that never entered a crew size gets "we don't know",
not a ``ZeroDivisionError`` and not a confident zero. See
:func:`app.services.reporting.revenue_target_service.backsolve_funnel` for the
same rule on the goal side.

The maths is a pure function over plain dataclasses (:func:`assemble_backlog`,
:func:`assemble_estimate_capacity`), mirroring
:func:`app.services.reporting.sales_performance_service.assemble_sales_performance`,
so every guard is unit-testable without a database.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import apply_workspace_scope, select_workspace_owned
from app.models.appointment import Appointment, AppointmentStatus
from app.models.field_service import Job, JobStatus
from app.models.revenue_target import RevenueTarget
from app.schemas.reporting import BacklogReport, EstimateCapacityReport
from app.services.reporting.revenue_target_service import (
    _as_float,
    _divisor,
    month_bounds,
    normalize_month,
)

# Work that is sold but not yet delivered. ``completed`` is delivered and
# ``cancelled`` was never sold, so neither is backlog. Applied in SQL (an
# index-friendly pre-filter over unbounded job history, via
# ``ix_field_service_jobs_workspace_status``) *and* in :func:`assemble_backlog`,
# which is the authority — this constant is the single statement of the rule.
OPEN_JOB_STATUSES = frozenset({JobStatus.UNSCHEDULED, JobStatus.SCHEDULED, JobStatus.IN_PROGRESS})

# Assumed hours for a job with no scheduled window. A half-day is the typical
# residential exterior-cleaning ticket; workspaces whose jobs run longer pass
# their own value rather than editing this.
DEFAULT_JOB_HOURS = 4.0

# Estimate utilization at which the bottleneck stops being lead flow and starts
# being the closer's calendar. Below 100% on purpose: an estimate calendar that
# is nominally "full" is already turning work away through cancellations,
# reschedules and drive time.
AT_CAPACITY_THRESHOLD_PCT = 85.0

# Appointment states that consumed a slot on the estimate calendar. A no-show
# still burned the hour and the drive; a cancellation released it.
BOOKED_APPOINTMENT_STATUSES = frozenset(
    {AppointmentStatus.SCHEDULED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW}
)


# --------------------------------------------------------------------------- #
# Pure backlog maths
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class JobFact:
    """One job flattened to the fields backlog reporting needs.

    Deliberately plain data (no ORM, no session) so the sizing and exclusion
    rules can be exercised with fabricated rows.
    """

    status: JobStatus
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None


def job_hours(fact: JobFact, *, default_hours: float = DEFAULT_JOB_HOURS) -> float:
    """Estimate one job's size in hours.

    Prefers the booked window, which is what dispatch actually committed to. A
    missing, zero-length or reversed window (an import artifact, or simply an
    unscheduled job) is not measurable, so it falls back to ``default_hours``. A
    non-positive ``default_hours`` would silently erase that work from the
    backlog, so it is refused in favour of :data:`DEFAULT_JOB_HOURS`.
    """
    fallback = _divisor(default_hours) or DEFAULT_JOB_HOURS
    if fact.scheduled_start is None or fact.scheduled_end is None:
        return fallback
    hours = (fact.scheduled_end - fact.scheduled_start).total_seconds() / 3600.0
    return hours if hours > 0 else fallback


def assemble_backlog(
    facts: Iterable[JobFact],
    *,
    as_of: date,
    weekly_capacity_hours: float | None,
    default_job_hours: float = DEFAULT_JOB_HOURS,
    alert_weeks: float | None = None,
) -> BacklogReport:
    """Build the backlog report from open jobs (pure).

    Closed jobs are filtered here rather than only in SQL, so "delivered and
    cancelled work is not backlog" lives in one testable place.

    ``backlog_weeks`` is ``None`` — never ``0`` and never an exception — when
    capacity is unset or non-positive: an owner who has not entered a crew size
    must be told the gauge is unreadable, not shown a full tank.
    """
    open_jobs = [fact for fact in facts if fact.status in OPEN_JOB_STATUSES]
    fallback_hours = _divisor(default_job_hours) or DEFAULT_JOB_HOURS

    backlog_hours = sum(job_hours(fact, default_hours=fallback_hours) for fact in open_jobs)
    # Work sold but never put on the calendar: its own operational risk, and the
    # part of the backlog whose size is a guess rather than a commitment.
    unscheduled = sum(1 for fact in open_jobs if fact.status is JobStatus.UNSCHEDULED)
    assumed = sum(
        1 for fact in open_jobs if fact.scheduled_start is None or fact.scheduled_end is None
    )

    capacity = _divisor(weekly_capacity_hours)
    weeks = round(backlog_hours / capacity, 2) if capacity else None
    threshold = _divisor(alert_weeks)

    return BacklogReport(
        as_of=as_of,
        backlog_hours=round(backlog_hours, 2),
        weekly_capacity_hours=capacity,
        backlog_weeks=weeks,
        job_count=len(open_jobs),
        unscheduled_job_count=unscheduled,
        assumed_duration_job_count=assumed,
        default_job_hours=fallback_hours,
        alert_weeks=threshold,
        below_alert_threshold=None if weeks is None or threshold is None else weeks < threshold,
    )


# --------------------------------------------------------------------------- #
# Pure estimate-capacity maths
# --------------------------------------------------------------------------- #
def assemble_estimate_capacity(
    *,
    period_month: date,
    booked: int,
    capacity: int | None,
) -> EstimateCapacityReport:
    """Build the estimate-capacity report (pure).

    ``utilization_pct`` and ``at_capacity`` are both ``None`` when no capacity is
    stored. Reporting ``at_capacity: false`` there would read as "plenty of room"
    off a number nobody ever set, which is the opposite of the truth this report
    exists to tell — the same ``bool | None`` convention as ``on_pace`` in
    :class:`app.schemas.revenue_target.RevenuePace`.
    """
    ceiling = _divisor(capacity)
    utilization = round(booked / ceiling * 100, 1) if ceiling else None

    return EstimateCapacityReport(
        period_month=normalize_month(period_month),
        booked=booked,
        capacity=capacity,
        utilization_pct=utilization,
        at_capacity=None if utilization is None else utilization >= AT_CAPACITY_THRESHOLD_PCT,
        at_capacity_threshold_pct=AT_CAPACITY_THRESHOLD_PCT,
    )


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
class CapacityService:
    """Workspace-scoped backlog and estimate-capacity reporting."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def compute_backlog(
        self,
        workspace_id: uuid.UUID,
        *,
        as_of: date | None = None,
        weekly_capacity_hours: float | None = None,
        default_job_hours: float = DEFAULT_JOB_HOURS,
    ) -> BacklogReport:
        """Report how many weeks of sold work the workspace has on the books.

        Args:
            workspace_id: Tenant to report on; every query is scoped to it.
            as_of: Reporting date (defaults to today). Backlog is a snapshot of
                open work, so this dates the answer rather than filtering it.
            weekly_capacity_hours: Override for the stored crew capacity. Lets a
                caller ask "what if I add a crew?" without writing a target, and
                is the way a workspace with no
                :class:`~app.models.revenue_target.RevenueTarget` row supplies
                the divisor at all.
            default_job_hours: Assumed size of a job with no scheduled window.

        Returns:
            A :class:`~app.schemas.reporting.BacklogReport`. ``backlog_weeks`` is
            ``None`` when no capacity is known from either source.
        """
        today = as_of or datetime.now(UTC).date()

        jobs = (
            (
                await self.db.execute(
                    select(Job.status, Job.scheduled_start, Job.scheduled_end).where(
                        Job.workspace_id == workspace_id,
                        Job.status.in_(OPEN_JOB_STATUSES),
                    )
                )
            )
            .tuples()
            .all()
        )
        facts = [
            JobFact(status=status, scheduled_start=start, scheduled_end=end)
            for status, start, end in jobs
        ]

        target = await self._capacity_target(workspace_id, today)
        stored_capacity = None if target is None else _as_float(target.crew_capacity_hours_per_week)

        return assemble_backlog(
            facts,
            as_of=today,
            weekly_capacity_hours=(
                weekly_capacity_hours if weekly_capacity_hours is not None else stored_capacity
            ),
            default_job_hours=default_job_hours,
            alert_weeks=None if target is None else _as_float(target.backlog_alert_weeks),
        )

    async def compute_estimate_capacity(
        self,
        workspace_id: uuid.UUID,
        month: date | None = None,
    ) -> EstimateCapacityReport:
        """Report a month's booked estimates against the closer's ceiling.

        ``month`` may be any date inside the month (defaults to the current one).
        The **whole** month is counted, future bookings included: a slot on next
        Thursday is capacity already spent, so pro-rating it to today — the way
        :meth:`app.services.reporting.RevenueTargetService.get_pace` pro-rates
        revenue — would understate how full the calendar is.

        Capacity comes from the month's own ``estimate_capacity_per_month``; an
        unset month reports ``booked`` with null ratios rather than guessing.
        """
        period = normalize_month(month or datetime.now(UTC).date())
        booked = await self._booked_estimates(workspace_id, period)

        target = await self._load_target(workspace_id, period)
        return assemble_estimate_capacity(
            period_month=period,
            booked=booked,
            capacity=None if target is None else target.estimate_capacity_per_month,
        )

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    async def _booked_estimates(self, workspace_id: uuid.UUID, period_month: date) -> int:
        """Count appointments occupying the month's estimate calendar.

        Counted by ``scheduled_at`` (when the slot is consumed), not by
        ``created_at`` (when it was booked), over a half-open ``[start, end)``
        window so a late-evening appointment on the last of the month counts.
        """
        first, last = month_bounds(period_month)
        start = datetime.combine(first, time.min, tzinfo=UTC)
        end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=UTC)

        count = (
            await self.db.execute(
                apply_workspace_scope(select(func.count()), Appointment, workspace_id).where(
                    Appointment.status.in_(BOOKED_APPOINTMENT_STATUSES),
                    Appointment.scheduled_at >= start,
                    Appointment.scheduled_at < end,
                )
            )
        ).scalar_one()
        return int(count or 0)

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

    async def _capacity_target(self, workspace_id: uuid.UUID, as_of: date) -> RevenueTarget | None:
        """Newest target at or before ``as_of`` that declares a crew capacity.

        Crew size is a standing fact about the business, not a monthly one, so it
        carries forward: an owner who set it in June must still get a readable
        gauge in July without re-entering it. Rows that left it null are skipped
        rather than shadowing an older row that has it — a target set only to
        record a revenue goal must not blank the backlog report.
        ``backlog_alert_weeks`` is read off this same row, as the companion
        setting to the capacity it thresholds.
        """
        result = await self.db.execute(
            select_workspace_owned(
                RevenueTarget,
                workspace_id,
                RevenueTarget.period_month <= normalize_month(as_of),
                RevenueTarget.crew_capacity_hours_per_week.is_not(None),
            )
            .order_by(RevenueTarget.period_month.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
