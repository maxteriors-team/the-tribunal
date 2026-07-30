"""Integration tests for the capacity queries (backlog and estimate capacity).

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits —
the service is read-only — so the transaction rolls back on close and the dev
database stays clean.

The maths is covered by ``test_capacity_service.py``; what needs Postgres is
everything the pure functions cannot prove:

- the SQL status pre-filter and the pure filter agree, so ``completed`` and
  ``cancelled`` jobs are excluded end-to-end and not merely in the assembler;
- ``crew_capacity_hours_per_week`` really is read off ``revenue_targets``, and its
  ``Numeric`` column survives as a usable ``float`` divisor;
- crew capacity carries forward from an earlier month, and a later target that
  left it null does not shadow the row that has it;
- appointments are counted by ``scheduled_at`` inside the month, cancellations
  excluded;
- every query stays inside one workspace.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus
from app.models.revenue_target import RevenueTarget
from app.models.workspace import Workspace
from app.services.reporting import CapacityService
from app.services.reporting.capacity_service import DEFAULT_JOB_HOURS

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

JULY = date(2026, 7, 1)
JUNE = date(2026, 6, 1)
IN_JULY = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Capacity", slug=f"cap-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db: AsyncSession, workspace_id: uuid.UUID) -> Contact:
    email = f"ada-{uuid.uuid4().hex[:6]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Ada",
        email=email,
        email_hash=hash_value(email),
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _job(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    status: JobStatus,
    hours: float | None = None,
) -> Job:
    """A job, optionally with a booked window ``hours`` long."""
    job = Job(
        workspace_id=workspace_id,
        contact_id=contact_id,
        title="Pressure wash",
        status=status,
        scheduled_start=IN_JULY if hours is not None else None,
        scheduled_end=IN_JULY + timedelta(hours=hours) if hours is not None else None,
    )
    db.add(job)
    await db.flush()
    return job


async def _target(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    period_month: date,
    crew_hours: float | None = None,
    estimates: int | None = None,
    alert_weeks: float | None = None,
) -> RevenueTarget:
    target = RevenueTarget(
        workspace_id=workspace_id,
        period_month=period_month,
        revenue_goal=130_000,
        crew_capacity_hours_per_week=crew_hours,
        estimate_capacity_per_month=estimates,
        backlog_alert_weeks=alert_weeks,
    )
    db.add(target)
    await db.flush()
    return target


async def _appointment(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    scheduled_at: datetime,
    status: AppointmentStatus = AppointmentStatus.SCHEDULED,
) -> Appointment:
    appointment = Appointment(
        workspace_id=workspace_id,
        contact_id=contact_id,
        scheduled_at=scheduled_at,
        status=status,
    )
    db.add(appointment)
    await db.flush()
    return appointment


# --------------------------------------------------------------------------- #
# Backlog
# --------------------------------------------------------------------------- #
async def test_backlog_of_an_empty_workspace_is_zero_hours_and_unknown_weeks() -> None:
    """A brand-new workspace: no jobs, no target, and no ZeroDivisionError."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)

        report = await CapacityService(db).compute_backlog(ws.id, as_of=JULY)

        assert report.job_count == 0
        assert report.unscheduled_job_count == 0
        assert report.backlog_hours == 0.0
        assert report.weekly_capacity_hours is None
        assert report.backlog_weeks is None
        assert report.below_alert_threshold is None
        assert report.as_of == JULY


async def test_backlog_counts_open_work_and_reads_capacity_from_the_target() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _target(db, ws.id, period_month=JULY, crew_hours=40, alert_weeks=3)

        # 8h + 12h booked, plus one unscheduled job at the 4h default = 24h.
        await _job(db, ws.id, contact.id, status=JobStatus.SCHEDULED, hours=8)
        await _job(db, ws.id, contact.id, status=JobStatus.IN_PROGRESS, hours=12)
        await _job(db, ws.id, contact.id, status=JobStatus.UNSCHEDULED)

        report = await CapacityService(db).compute_backlog(ws.id, as_of=JULY)

        assert report.job_count == 3
        assert report.unscheduled_job_count == 1
        assert report.assumed_duration_job_count == 1
        assert report.backlog_hours == 24.0
        # Numeric(10,2) arrives as Decimal; it must reach the maths as a float.
        assert report.weekly_capacity_hours == 40.0
        assert report.backlog_weeks == 0.6
        assert report.alert_weeks == 3.0
        assert report.below_alert_threshold is True


async def test_backlog_excludes_completed_and_cancelled_jobs_in_sql() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _target(db, ws.id, period_month=JULY, crew_hours=40)

        await _job(db, ws.id, contact.id, status=JobStatus.SCHEDULED, hours=8)
        # Big closed jobs: if either leaked in, the weeks number would double.
        await _job(db, ws.id, contact.id, status=JobStatus.COMPLETED, hours=40)
        await _job(db, ws.id, contact.id, status=JobStatus.CANCELLED, hours=40)
        await _job(db, ws.id, contact.id, status=JobStatus.CANCELLED)

        report = await CapacityService(db).compute_backlog(ws.id, as_of=JULY)

        assert report.job_count == 1
        assert report.backlog_hours == 8.0
        assert report.backlog_weeks == 0.2


async def test_backlog_weeks_is_none_when_the_target_leaves_capacity_unset() -> None:
    """A goal without a crew size still reports hours, but cannot report weeks."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _target(db, ws.id, period_month=JULY, crew_hours=None)
        await _job(db, ws.id, contact.id, status=JobStatus.SCHEDULED, hours=8)

        report = await CapacityService(db).compute_backlog(ws.id, as_of=JULY)

        assert report.backlog_hours == 8.0
        assert report.weekly_capacity_hours is None
        assert report.backlog_weeks is None


async def test_backlog_carries_crew_capacity_forward_from_an_earlier_month() -> None:
    """Crew size is a standing fact; July must not need it re-entered."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _target(db, ws.id, period_month=JUNE, crew_hours=40)
        # July's target records a goal only — it must not blank the gauge.
        await _target(db, ws.id, period_month=JULY, crew_hours=None)
        await _job(db, ws.id, contact.id, status=JobStatus.SCHEDULED, hours=40)

        report = await CapacityService(db).compute_backlog(ws.id, as_of=date(2026, 7, 15))

        assert report.weekly_capacity_hours == 40.0
        assert report.backlog_weeks == 1.0


async def test_backlog_ignores_capacity_set_for_a_later_month() -> None:
    """A capacity planned for August cannot describe June's crew."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _target(db, ws.id, period_month=date(2026, 8, 1), crew_hours=80)
        await _job(db, ws.id, contact.id, status=JobStatus.SCHEDULED, hours=8)

        report = await CapacityService(db).compute_backlog(ws.id, as_of=JUNE)

        assert report.weekly_capacity_hours is None
        assert report.backlog_weeks is None


async def test_backlog_capacity_override_beats_the_stored_target() -> None:
    """The "what if I add a crew?" path, and the only path with no target row."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _target(db, ws.id, period_month=JULY, crew_hours=40)
        await _job(db, ws.id, contact.id, status=JobStatus.SCHEDULED, hours=80)

        service = CapacityService(db)
        stored = await service.compute_backlog(ws.id, as_of=JULY)
        doubled = await service.compute_backlog(ws.id, as_of=JULY, weekly_capacity_hours=80)

        assert stored.backlog_weeks == 2.0
        assert doubled.weekly_capacity_hours == 80.0
        assert doubled.backlog_weeks == 1.0


async def test_backlog_honours_a_custom_default_job_size_end_to_end() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _job(db, ws.id, contact.id, status=JobStatus.UNSCHEDULED)

        service = CapacityService(db)
        default = await service.compute_backlog(ws.id, as_of=JULY, weekly_capacity_hours=40)
        longer = await service.compute_backlog(
            ws.id, as_of=JULY, weekly_capacity_hours=40, default_job_hours=10
        )

        assert default.backlog_hours == DEFAULT_JOB_HOURS
        assert longer.backlog_hours == 10.0
        assert longer.default_job_hours == 10.0


async def test_backlog_never_leaks_another_workspaces_jobs_or_capacity() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        contact = await _contact(db, ws.id)
        other_contact = await _contact(db, other.id)

        await _target(db, ws.id, period_month=JULY, crew_hours=40)
        await _target(db, other.id, period_month=JULY, crew_hours=999)
        await _job(db, ws.id, contact.id, status=JobStatus.SCHEDULED, hours=8)
        await _job(db, other.id, other_contact.id, status=JobStatus.SCHEDULED, hours=500)

        report = await CapacityService(db).compute_backlog(ws.id, as_of=JULY)

        assert report.job_count == 1
        assert report.backlog_hours == 8.0
        assert report.weekly_capacity_hours == 40.0


# --------------------------------------------------------------------------- #
# Estimate capacity
# --------------------------------------------------------------------------- #
async def test_estimate_capacity_of_an_empty_workspace_is_zero_and_unknown() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)

        report = await CapacityService(db).compute_estimate_capacity(ws.id, JULY)

        assert report.period_month == JULY
        assert report.booked == 0
        assert report.capacity is None
        assert report.utilization_pct is None
        assert report.at_capacity is None


async def test_estimate_capacity_counts_the_month_and_trips_the_hire_trigger() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _target(db, ws.id, period_month=JULY, estimates=4)

        # Both month edges must count: first day at midnight, last day at 23:59.
        await _appointment(db, ws.id, contact.id, scheduled_at=datetime(2026, 7, 1, tzinfo=UTC))
        await _appointment(
            db, ws.id, contact.id, scheduled_at=datetime(2026, 7, 31, 23, 59, tzinfo=UTC)
        )
        # A held slot counts whether it was run or no-showed.
        await _appointment(
            db, ws.id, contact.id, scheduled_at=IN_JULY, status=AppointmentStatus.COMPLETED
        )
        await _appointment(
            db, ws.id, contact.id, scheduled_at=IN_JULY, status=AppointmentStatus.NO_SHOW
        )
        # A cancellation released the slot, so it consumed no capacity.
        await _appointment(
            db, ws.id, contact.id, scheduled_at=IN_JULY, status=AppointmentStatus.CANCELLED
        )
        # Neighbouring months are a different report.
        await _appointment(
            db, ws.id, contact.id, scheduled_at=datetime(2026, 6, 30, 23, 59, tzinfo=UTC)
        )
        await _appointment(db, ws.id, contact.id, scheduled_at=datetime(2026, 8, 1, tzinfo=UTC))

        # Any day inside July addresses the month.
        report = await CapacityService(db).compute_estimate_capacity(ws.id, date(2026, 7, 14))

        assert report.period_month == JULY
        assert report.booked == 4
        assert report.capacity == 4
        assert report.utilization_pct == 100.0
        assert report.at_capacity is True


async def test_estimate_capacity_does_not_carry_forward_a_previous_month() -> None:
    """Unlike crew size, an estimate ceiling is set per month and not inherited."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _target(db, ws.id, period_month=JUNE, estimates=60)

        report = await CapacityService(db).compute_estimate_capacity(ws.id, JULY)

        assert report.capacity is None
        assert report.utilization_pct is None


async def test_estimate_capacity_never_leaks_another_workspaces_appointments() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        contact = await _contact(db, ws.id)
        other_contact = await _contact(db, other.id)
        await _target(db, ws.id, period_month=JULY, estimates=60)

        await _appointment(db, ws.id, contact.id, scheduled_at=IN_JULY)
        for _ in range(5):
            await _appointment(db, other.id, other_contact.id, scheduled_at=IN_JULY)

        report = await CapacityService(db).compute_estimate_capacity(ws.id, JULY)

        assert report.booked == 1
        assert report.utilization_pct == pytest.approx(1.7)
