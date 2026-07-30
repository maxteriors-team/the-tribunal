"""End-to-end DB-backed proof for the ``backlog_below_threshold`` trigger.

Marked ``integration`` (run with ``-m integration``); these hit the real Postgres
engine, so they exercise what mocks cannot:

* ``CapacityService.compute_backlog`` really reading open jobs and the carried-
  forward ``crew_capacity_hours_per_week`` off ``revenue_targets``;
* a fire really flipping a ``DripCampaign`` to ``active`` — the whole point of
  the feature: thin backlog in, demand generation out;
* the contact-less ``AutomationExecution`` row inserting **twice** without
  tripping ``uq_automation_execution_contact`` (Postgres treats NULLs as
  distinct), which is why the cooldown, not a unique index, is what bounds
  re-fires;
* a workspace with no crew capacity producing no fire at all.

Each test owns a throwaway workspace and deletes it (cascade) at the end, so a
local dev database is left exactly as it was found.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal, engine
from app.models.automation import Automation
from app.models.automation_execution import AutomationExecution
from app.models.contact import Contact
from app.models.drip_campaign import DripCampaign, DripCampaignStatus
from app.models.field_service import Job, JobStatus
from app.models.revenue_target import RevenueTarget
from app.models.workspace import Workspace
from app.services.automations.conditions import CONDITION_BACKLOG_BELOW_THRESHOLD
from app.workers.automation_worker import AutomationWorker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# 40 sellable crew hours a week: one job with a 40-hour window is one week of work.
WEEKLY_CAPACITY = 40.0


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared asyncpg pool around each test (see sibling suites)."""
    await engine.dispose()
    yield
    await engine.dispose()


# --------------------------------------------------------------------------- #
# Builders                                                                     #
# --------------------------------------------------------------------------- #


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Backlog", slug=f"backlog-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _capacity(db, workspace_id: uuid.UUID, hours_per_week: float | None) -> None:
    """Record the crew capacity that makes the backlog gauge readable."""
    db.add(
        RevenueTarget(
            workspace_id=workspace_id,
            period_month=date.today().replace(day=1),
            revenue_goal=50_000,
            crew_capacity_hours_per_week=hours_per_week,
        )
    )
    await db.flush()


async def _booked_job(db, workspace_id: uuid.UUID, *, hours: float) -> Job:
    """One scheduled job of ``hours`` — sold work that is not yet delivered."""
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Grace",
        last_name="Hopper",
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()

    start = datetime.now(UTC) + timedelta(days=1)
    job = Job(
        workspace_id=workspace_id,
        contact_id=contact.id,
        title="Gutter clean",
        status=JobStatus.SCHEDULED,
        scheduled_start=start,
        scheduled_end=start + timedelta(hours=hours),
    )
    db.add(job)
    await db.flush()
    return job


async def _drip(db, workspace_id: uuid.UUID) -> DripCampaign:
    campaign = DripCampaign(
        workspace_id=workspace_id,
        name="Past-customer reactivation",
        from_phone_number="+15550001111",
        status=DripCampaignStatus.DRAFT,
        sequence_steps=[
            {"step": 0, "delay_days": 0, "message": "Hi {first_name}", "type": "offer"}
        ],
    )
    db.add(campaign)
    await db.flush()
    return campaign


async def _automation(
    db,
    workspace_id: uuid.UUID,
    drip_campaign_id: uuid.UUID,
    *,
    threshold_weeks: float = 4.0,
    cooldown_days: int = 14,
) -> Automation:
    automation = Automation(
        workspace_id=workspace_id,
        name="Dry pipeline -> reactivation drip",
        trigger_type=CONDITION_BACKLOG_BELOW_THRESHOLD,
        trigger_config={"threshold_weeks": threshold_weeks, "cooldown_days": cooldown_days},
        actions=[
            {
                "type": "start_drip_campaign",
                "config": {"drip_campaign_id": str(drip_campaign_id)},
            }
        ],
        is_active=True,
    )
    db.add(automation)
    await db.flush()
    return automation


async def _execution_count(db, automation_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(AutomationExecution.id)).where(
            AutomationExecution.automation_id == automation_id
        )
    )
    return int(result.scalar() or 0)


async def _cleanup(db, workspace_id: uuid.UUID) -> None:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is not None:
        await db.delete(workspace)
    await db.commit()


async def _evaluate(db, automation: Automation) -> None:
    """Run one poll cycle's evaluation for a single automation."""
    worker = AutomationWorker()
    await worker._evaluate_automation(automation, db)
    await db.flush()


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


async def test_thin_backlog_starts_the_reactivation_drip() -> None:
    """One week of booked work against a four-week threshold: fire."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        try:
            await _capacity(db, ws.id, WEEKLY_CAPACITY)
            await _booked_job(db, ws.id, hours=WEEKLY_CAPACITY)  # 1.0 weeks
            drip = await _drip(db, ws.id)
            automation = await _automation(db, ws.id, drip.id)
            await db.commit()

            await _evaluate(db, automation)
            await db.commit()

            await db.refresh(drip)
            assert drip.status == DripCampaignStatus.ACTIVE
            assert drip.started_at is not None
            assert automation.last_triggered_at is not None
            assert await _execution_count(db, automation.id) == 1
        finally:
            await _cleanup(db, ws.id)


async def test_healthy_backlog_leaves_the_drip_alone() -> None:
    """Ten weeks booked: the calendar is full, spend nothing."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        try:
            await _capacity(db, ws.id, WEEKLY_CAPACITY)
            await _booked_job(db, ws.id, hours=WEEKLY_CAPACITY * 10)  # 10.0 weeks
            drip = await _drip(db, ws.id)
            automation = await _automation(db, ws.id, drip.id)
            await db.commit()

            await _evaluate(db, automation)
            await db.commit()

            await db.refresh(drip)
            assert drip.status == DripCampaignStatus.DRAFT
            assert automation.last_triggered_at is None
            assert await _execution_count(db, automation.id) == 0
        finally:
            await _cleanup(db, ws.id)


async def test_unset_crew_capacity_never_fires() -> None:
    """No capacity row value -> unreadable gauge -> no campaign, ever.

    The workspace has zero open jobs, so a "None means zero" bug would read this
    as an empty backlog and blast the list.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        try:
            await _capacity(db, ws.id, None)
            drip = await _drip(db, ws.id)
            automation = await _automation(db, ws.id, drip.id)
            await db.commit()

            await _evaluate(db, automation)
            await db.commit()

            await db.refresh(drip)
            assert drip.status == DripCampaignStatus.DRAFT
            assert automation.last_triggered_at is None
            assert await _execution_count(db, automation.id) == 0
        finally:
            await _cleanup(db, ws.id)


async def test_cooldown_bounds_repeat_cycles_and_then_expires() -> None:
    """Three cycles: fire, silence, fire — with real execution rows.

    The second fire proves two contact-less executions coexist under
    ``uq_automation_execution_contact`` (NULLs are distinct in Postgres), so the
    cooldown is the only thing standing between a slow month and a daily blast.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        try:
            await _capacity(db, ws.id, WEEKLY_CAPACITY)
            await _booked_job(db, ws.id, hours=WEEKLY_CAPACITY / 2)  # 0.5 weeks
            drip = await _drip(db, ws.id)
            automation = await _automation(db, ws.id, drip.id, cooldown_days=7)
            await db.commit()

            await _evaluate(db, automation)
            await db.commit()
            first_fire = automation.last_triggered_at
            assert first_fire is not None

            # Cycle two, moments later: still thin, still quiet.
            await _evaluate(db, automation)
            await db.commit()
            assert automation.last_triggered_at == first_fire
            assert await _execution_count(db, automation.id) == 1

            # Cycle three, after the cooldown: fires again.
            automation.last_triggered_at = datetime.now(UTC) - timedelta(days=8)
            await db.commit()
            await _evaluate(db, automation)
            await db.commit()

            assert automation.last_triggered_at is not None
            assert automation.last_triggered_at > datetime.now(UTC) - timedelta(minutes=5)
            assert await _execution_count(db, automation.id) == 2
        finally:
            await _cleanup(db, ws.id)
