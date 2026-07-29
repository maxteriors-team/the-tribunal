"""Integration tests for the revenue-target storage and actuals queries.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). The maths is covered by ``test_revenue_target_service.py``;
what needs Postgres is everything the ORM alone cannot prove:

- the ``ON CONFLICT`` upsert really is idempotent per month, and really does
  update rather than insert a second row;
- ``uq_revenue_targets_workspace_month`` is enforced by the *database*, not just
  declared on the model — that constraint is what the upsert keys on;
- the check constraint refuses a ``period_month`` that is not the 1st, catching
  rows a script writes around the service;
- the pace actuals join the right three tables over the right window, and stay
  inside one workspace.

The service commits (it is the write path), so each test cleans up its own
workspace; the cascading FK takes the targets, contacts, quotes and
opportunities with it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.pipeline import Pipeline
from app.models.quote import Quote
from app.models.revenue_target import RevenueTarget
from app.models.workspace import Workspace
from app.schemas.revenue_target import RevenueTargetBulkUpsert, RevenueTargetUpsert
from app.services.exceptions import NotFoundError
from app.services.reporting import RevenueTargetService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

JUNE = date(2026, 6, 1)
JANUARY = date(2026, 1, 1)
IN_JUNE = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Targets", slug=f"tgt-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _cleanup(db: AsyncSession, *workspaces: Workspace) -> None:
    """Drop the test workspaces; every row under test cascades away with them."""
    for ws in workspaces:
        await db.delete(await db.merge(ws))
    await db.commit()


async def _contact(db: AsyncSession, workspace_id: uuid.UUID, *, created_at: datetime) -> Contact:
    email = f"lead-{uuid.uuid4().hex[:6]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Ada",
        email=email,
        email_hash=hash_value(email),
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
        created_at=created_at,
    )
    db.add(contact)
    await db.flush()
    return contact


async def _quote(
    db: AsyncSession, workspace_id: uuid.UUID, *, status: str, created_at: datetime
) -> Quote:
    quote = Quote(
        workspace_id=workspace_id,
        number=f"QUO-{uuid.uuid4().hex[:6]}",
        subtotal=1_000,
        total=1_000,
        status=status,
        created_at=created_at,
    )
    db.add(quote)
    await db.flush()
    return quote


async def _won_opportunity(
    db: AsyncSession, workspace_id: uuid.UUID, *, amount: float, closed_date: date
) -> Opportunity:
    pipeline = Pipeline(workspace_id=workspace_id, name="Sales")
    db.add(pipeline)
    await db.flush()

    opportunity = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline.id,
        name="Deal",
        amount=amount,
        status="won",
        closed_date=closed_date,
    )
    db.add(opportunity)
    await db.flush()
    return opportunity


def _june_target(**overrides: object) -> RevenueTargetUpsert:
    values: dict[str, object] = {
        "period_month": JUNE,
        "revenue_goal": 130_000,
        "target_avg_job_value": 1_300,
        "target_close_rate": 40,
        "assumed_sat_rate": 50,
    }
    values.update(overrides)
    return RevenueTargetUpsert(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Upsert
# --------------------------------------------------------------------------- #
async def test_upsert_replaces_the_month_instead_of_adding_a_second_row() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        service = RevenueTargetService(db)

        created = await service.upsert_target(ws.id, _june_target())
        # Same month addressed by a mid-month date: it must find June, not make one.
        updated = await service.upsert_target(
            ws.id, _june_target(period_month=date(2026, 6, 14), revenue_goal=145_000)
        )

        assert created.period_month == JUNE
        assert updated.period_month == JUNE
        assert updated.id == created.id
        assert updated.revenue_goal == 145_000.0
        assert updated.created_at == created.created_at
        # The Python-side ``onupdate`` never fires for ON CONFLICT, so the
        # upsert has to bump this itself.
        assert updated.updated_at >= created.updated_at

        listed = await service.list_targets(ws.id)
        assert listed.total == 1

        await _cleanup(db, ws)


async def test_bulk_upsert_writes_a_season_then_revises_it() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        service = RevenueTargetService(db)

        await service.bulk_upsert(
            ws.id,
            RevenueTargetBulkUpsert(
                targets=[
                    RevenueTargetUpsert(period_month=JANUARY, revenue_goal=45_000),
                    _june_target(),
                ]
            ),
        )
        # A seasonal business revises one month and adds another; the untouched
        # month must survive the second call.
        revised = await service.bulk_upsert(
            ws.id,
            RevenueTargetBulkUpsert(
                targets=[
                    _june_target(revenue_goal=150_000),
                    RevenueTargetUpsert(period_month=date(2026, 12, 1), revenue_goal=60_000),
                ]
            ),
        )

        assert [item.period_month for item in revised.items] == [JUNE, date(2026, 12, 1)]

        listed = await service.list_targets(ws.id)
        assert [item.period_month for item in listed.items] == [
            JANUARY,
            JUNE,
            date(2026, 12, 1),
        ]
        assert [item.revenue_goal for item in listed.items] == [45_000.0, 150_000.0, 60_000.0]

        await _cleanup(db, ws)


async def test_list_can_narrow_to_one_calendar_year() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        service = RevenueTargetService(db)

        await service.bulk_upsert(
            ws.id,
            RevenueTargetBulkUpsert(
                targets=[
                    RevenueTargetUpsert(period_month=date(2025, 12, 1), revenue_goal=50_000),
                    RevenueTargetUpsert(period_month=JANUARY, revenue_goal=45_000),
                    RevenueTargetUpsert(period_month=date(2026, 12, 1), revenue_goal=60_000),
                    RevenueTargetUpsert(period_month=date(2027, 1, 1), revenue_goal=70_000),
                ]
            ),
        )

        listed = await service.list_targets(ws.id, year=2026)

        assert [item.period_month for item in listed.items] == [JANUARY, date(2026, 12, 1)]

        await _cleanup(db, ws)


async def test_targets_are_workspace_isolated() -> None:
    async with AsyncSessionLocal() as db:
        mine = await _workspace(db)
        theirs = await _workspace(db)
        service = RevenueTargetService(db)

        await service.upsert_target(mine.id, _june_target())
        await service.upsert_target(theirs.id, _june_target(revenue_goal=999_000))

        listed = await service.list_targets(mine.id)

        assert listed.total == 1
        assert listed.items[0].revenue_goal == 130_000.0

        await _cleanup(db, mine, theirs)


async def test_get_and_delete_report_a_month_that_was_never_set() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        service = RevenueTargetService(db)

        with pytest.raises(NotFoundError, match="2026-06"):
            await service.get_target(ws.id, JUNE)
        with pytest.raises(NotFoundError):
            await service.delete_target(ws.id, JUNE)

        await service.upsert_target(ws.id, _june_target())
        # A mid-month date still addresses June on the read path too.
        assert (await service.get_target(ws.id, date(2026, 6, 30))).revenue_goal == 130_000.0

        await service.delete_target(ws.id, date(2026, 6, 30))
        assert (await service.list_targets(ws.id)).total == 0

        await _cleanup(db, ws)


# --------------------------------------------------------------------------- #
# Storage constraints
# --------------------------------------------------------------------------- #
async def test_database_refuses_two_targets_for_one_month() -> None:
    """The upsert keys on this constraint, so the DB must actually enforce it."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        db.add(RevenueTarget(workspace_id=ws.id, period_month=JUNE, revenue_goal=130_000))
        await db.flush()

        db.add(RevenueTarget(workspace_id=ws.id, period_month=JUNE, revenue_goal=145_000))
        with pytest.raises(IntegrityError, match="uq_revenue_targets_workspace_month"):
            await db.flush()

        # Nothing here was committed, so the rollback *is* the cleanup.
        await db.rollback()


async def test_database_refuses_a_period_month_that_is_not_the_first() -> None:
    """Service-side normalization cannot protect rows a script writes directly."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        db.add(
            RevenueTarget(
                workspace_id=ws.id, period_month=date(2026, 6, 14), revenue_goal=130_000
            )
        )

        with pytest.raises(IntegrityError, match="period_month_is_first_of_month"):
            await db.flush()

        await db.rollback()


# --------------------------------------------------------------------------- #
# Pace actuals
# --------------------------------------------------------------------------- #
async def test_pace_counts_the_month_actuals_from_the_live_crm() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        service = RevenueTargetService(db)
        await service.upsert_target(ws.id, _june_target())

        # Leads: contacts created in June. The May one must not leak in.
        await _contact(db, ws.id, created_at=IN_JUNE)
        await _contact(db, ws.id, created_at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC))
        await _contact(db, ws.id, created_at=datetime(2026, 5, 31, 23, 59, tzinfo=UTC))

        # Estimates: quotes that left draft. The draft never reached a customer.
        await _quote(db, ws.id, status="sent", created_at=IN_JUNE)
        await _quote(db, ws.id, status="approved", created_at=IN_JUNE)
        await _quote(db, ws.id, status="draft", created_at=IN_JUNE)

        # Sold: closed-won opportunities, the same source as the dashboard.
        await _won_opportunity(db, ws.id, amount=40_000, closed_date=date(2026, 6, 5))
        await _won_opportunity(db, ws.id, amount=25_000, closed_date=date(2026, 6, 12))
        await _won_opportunity(db, ws.id, amount=99_000, closed_date=date(2026, 7, 1))

        pace = await service.get_pace(ws.id, JUNE, today=date(2026, 6, 15))

        assert pace.has_target is True
        assert pace.revenue_sold_to_date == 65_000.0
        assert (pace.days_elapsed, pace.days_in_month) == (15, 30)
        assert pace.projected_month_end == 130_000.0
        assert pace.on_pace is True

        stages = {stage.stage: stage for stage in pace.stages}
        assert stages["leads"].actual == 2
        assert stages["estimates"].actual == 2
        assert stages["sold"].actual == 2

        await _cleanup(db, ws)


async def test_pace_ignores_work_dated_after_today() -> None:
    """"To date" means to date: a deal closed later this month is not sold yet."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        service = RevenueTargetService(db)
        await service.upsert_target(ws.id, _june_target())

        await _won_opportunity(db, ws.id, amount=10_000, closed_date=date(2026, 6, 3))
        await _won_opportunity(db, ws.id, amount=50_000, closed_date=date(2026, 6, 28))
        await _contact(db, ws.id, created_at=datetime(2026, 6, 27, 9, 0, tzinfo=UTC))

        pace = await service.get_pace(ws.id, JUNE, today=date(2026, 6, 10))

        assert pace.revenue_sold_to_date == 10_000.0
        assert {stage.stage: stage.actual for stage in pace.stages}["leads"] == 0

        await _cleanup(db, ws)


async def test_pace_reports_actuals_for_a_month_with_no_target() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _won_opportunity(db, ws.id, amount=12_000, closed_date=date(2026, 6, 4))

        pace = await RevenueTargetService(db).get_pace(ws.id, JUNE, today=date(2026, 6, 15))

        assert pace.has_target is False
        assert pace.revenue_goal is None
        assert pace.revenue_sold_to_date == 12_000.0
        assert all(stage.required is None for stage in pace.stages)

        await _cleanup(db, ws)


async def test_pace_never_counts_another_workspaces_revenue() -> None:
    async with AsyncSessionLocal() as db:
        mine = await _workspace(db)
        theirs = await _workspace(db)
        await _won_opportunity(db, mine.id, amount=10_000, closed_date=date(2026, 6, 4))
        await _won_opportunity(db, theirs.id, amount=500_000, closed_date=date(2026, 6, 4))
        await _contact(db, theirs.id, created_at=IN_JUNE)

        pace = await RevenueTargetService(db).get_pace(mine.id, JUNE, today=date(2026, 6, 15))

        assert pace.revenue_sold_to_date == 10_000.0
        assert {stage.stage: stage.actual for stage in pace.stages}["leads"] == 0

        await _cleanup(db, mine, theirs)
