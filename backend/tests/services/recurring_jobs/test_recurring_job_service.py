"""Integration tests for :class:`app.services.recurring_jobs.RecurringJobService`.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: the recurrence date math, CRUD, on-demand ``run_template`` generation
(including the per-occurrence idempotency guard and default-technician tagging),
the worker ``materialize_due`` lead-window behaviour, and cross-workspace 404s.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from sqlalchemy import select

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import Job, JobAssignment, JobStatus, Technician
from app.models.recurring_job import RecurrenceFrequency, RecurringJobTemplate
from app.models.workspace import Workspace
from app.schemas.recurring_job import RecurringJobTemplateCreate
from app.services.recurring_jobs import RecurringJobService, advance_occurrence

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Recurring", slug=f"recur-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
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


async def _technician(db, workspace_id: uuid.UUID) -> Technician:
    tech = Technician(workspace_id=workspace_id, name=f"Tech {uuid.uuid4().hex[:6]}")
    db.add(tech)
    await db.flush()
    return tech


def _create_payload(contact_id: int, next_run_at: datetime, **overrides) -> dict:
    base = {
        "contact_id": contact_id,
        "title": "Quarterly HVAC service",
        "frequency": RecurrenceFrequency.QUARTERLY,
        "next_run_at": next_run_at,
        "duration_minutes": 120,
        "generate_days_ahead": 14,
    }
    base.update(overrides)
    return RecurringJobTemplateCreate(**base).model_dump()


async def _jobs_for_template(db, template_id: uuid.UUID) -> list[Job]:
    rows = (
        await db.execute(select(Job).where(Job.recurring_template_id == template_id))
    ).scalars().all()
    return list(rows)


# --------------------------------------------------------------------------- #
# Recurrence math (pure function)
# --------------------------------------------------------------------------- #
async def test_advance_occurrence_handles_every_frequency() -> None:
    base = datetime(2026, 1, 31, 9, 0, tzinfo=UTC)
    assert advance_occurrence(base, "weekly", 1) == base + timedelta(weeks=1)
    assert advance_occurrence(base, "weekly", 2) == base + timedelta(weeks=2)
    assert advance_occurrence(base, "biweekly", 1) == base + timedelta(weeks=2)
    # Calendar-aware: Jan 31 + 1 month rolls to Feb 28 (not an invalid Feb 31).
    assert advance_occurrence(base, "monthly", 1) == datetime(2026, 2, 28, 9, 0, tzinfo=UTC)
    assert advance_occurrence(base, "quarterly", 1) == base + relativedelta(months=3)
    assert advance_occurrence(base, "yearly", 1) == datetime(2027, 1, 31, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
async def test_create_and_list_template() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        svc = RecurringJobService(db)

        start = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
        created = await svc.create(ws.id, _create_payload(contact.id, start))
        assert created.frequency == RecurrenceFrequency.QUARTERLY
        assert created.next_run_at == start
        assert created.is_active is True

        listed = await svc.list(ws.id)
        assert listed["total"] == 1
        active_only = await svc.list(ws.id, is_active=True)
        assert active_only["total"] == 1


async def test_create_rejects_foreign_technician() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _workspace(db)
        ws_b = await _workspace(db)
        contact = await _contact(db, ws_a.id)
        foreign_tech = await _technician(db, ws_b.id)
        svc = RecurringJobService(db)

        start = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
        payload = _create_payload(contact.id, start, default_technician_ids=[foreign_tech.id])
        with pytest.raises(HTTPException):
            await svc.create(ws_a.id, payload)


# --------------------------------------------------------------------------- #
# On-demand generation (run_template)
# --------------------------------------------------------------------------- #
async def test_run_template_generates_job_and_advances_cursor() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        tech = await _technician(db, ws.id)
        svc = RecurringJobService(db)

        # next_run far in the future → beyond the lead window, but force=True
        # (the operator "generate next now" action) materializes it anyway.
        start = datetime(2099, 1, 1, 9, 0, tzinfo=UTC)
        tpl = await svc.create(
            ws.id, _create_payload(contact.id, start, default_technician_ids=[tech.id])
        )

        result = await svc.run_template(tpl.id, ws.id)
        assert result["created"] == 1
        # Cursor advanced one quarter past the first occurrence.
        assert result["template"].next_run_at == start + relativedelta(months=3)
        assert result["template"].last_run_at is not None

        jobs = await _jobs_for_template(db, tpl.id)
        assert len(jobs) == 1
        job = jobs[0]
        assert job.status == JobStatus.SCHEDULED
        assert job.scheduled_start == start
        assert job.scheduled_end == start + timedelta(minutes=120)
        assert job.contact_id == contact.id

        # Default technician was tagged onto the generated job.
        assignments = (
            await db.execute(select(JobAssignment).where(JobAssignment.job_id == job.id))
        ).scalars().all()
        assert [a.technician_id for a in assignments] == [tech.id]


async def test_run_template_is_idempotent_per_occurrence() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        svc = RecurringJobService(db)

        start = datetime(2099, 3, 1, 9, 0, tzinfo=UTC)
        tpl = await svc.create(ws.id, _create_payload(contact.id, start))
        await svc.run_template(tpl.id, ws.id)
        assert len(await _jobs_for_template(db, tpl.id)) == 1

        # Rewind the cursor to the already-generated occurrence and run again:
        # the per-occurrence guard prevents a duplicate even though the cursor
        # points back at a start that already has a job.
        orm_tpl = await db.get(RecurringJobTemplate, tpl.id)
        orm_tpl.next_run_at = start
        await db.flush()

        result = await svc.run_template(tpl.id, ws.id)
        assert result["created"] == 0
        assert len(await _jobs_for_template(db, tpl.id)) == 1


# --------------------------------------------------------------------------- #
# Worker path (materialize_due)
# --------------------------------------------------------------------------- #
async def test_materialize_due_respects_lead_window() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        svc = RecurringJobService(db)

        now = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)

        # Due soon (within the 14-day lead window) → generated.
        due = await svc.create(
            ws.id, _create_payload(contact.id, now + timedelta(days=3))
        )
        # Far out (beyond the lead window) → not yet generated.
        far = await svc.create(
            ws.id, _create_payload(contact.id, now + timedelta(days=90))
        )

        await svc.materialize_due(now=now)

        assert len(await _jobs_for_template(db, due.id)) == 1
        assert len(await _jobs_for_template(db, far.id)) == 0

        # Re-running the same pass creates nothing extra (idempotent per period).
        await svc.materialize_due(now=now)
        assert len(await _jobs_for_template(db, due.id)) == 1


async def test_materialize_due_skips_inactive_templates() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        svc = RecurringJobService(db)

        now = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
        tpl = await svc.create(
            ws.id, _create_payload(contact.id, now + timedelta(days=1), is_active=False)
        )

        await svc.materialize_due(now=now)
        assert len(await _jobs_for_template(db, tpl.id)) == 0


# --------------------------------------------------------------------------- #
# Tenant isolation
# --------------------------------------------------------------------------- #
async def test_cross_workspace_template_is_404() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _workspace(db)
        ws_b = await _workspace(db)
        contact = await _contact(db, ws_a.id)
        svc = RecurringJobService(db)

        start = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
        tpl = await svc.create(ws_a.id, _create_payload(contact.id, start))

        with pytest.raises(HTTPException):
            await svc.get(tpl.id, ws_b.id)
        with pytest.raises(HTTPException):
            await svc.run_template(tpl.id, ws_b.id)
