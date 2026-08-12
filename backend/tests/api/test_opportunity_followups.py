"""Notes and tasks belong to the deal, not to the person.

A contact can have five jobs in flight; hanging every follow-up off the contact
makes "call them back about the gutters" indistinguishable from "call them back
about the roof". These tests pin the follow-up to the opportunity and prove it
survives the round trip the detail sheet actually makes.

Marked ``integration``: task ordering is done in SQL (NULLS LAST) and the detail
payload depends on eager loading, neither of which a mocked session can show.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.pipeline import Pipeline, PipelineStage
from app.models.workspace import Workspace
from app.schemas.opportunity import (
    OpportunityNoteCreate,
    OpportunityTaskCreate,
    OpportunityTaskUpdate,
)
from app.services.opportunities import OpportunityService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Deals", slug=f"dl-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _opportunity(db, workspace_id: uuid.UUID) -> Opportunity:
    pipeline = Pipeline(workspace_id=workspace_id, name="Sales")
    db.add(pipeline)
    await db.flush()
    stage = PipelineStage(pipeline_id=pipeline.id, name="Quote", order=0, probability=50)
    db.add(stage)
    await db.flush()

    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Lisa",
        last_name="Shelton",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        status="qualified",
    )
    db.add(contact)
    await db.flush()

    opp = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline.id,
        stage_id=stage.id,
        name="Gutter clean",
        primary_contact_id=contact.id,
    )
    db.add(opp)
    await db.flush()
    return opp


class TestNotes:
    async def test_note_lands_on_the_opportunity_timeline(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)

            await service.add_note(
                ws.id, opp.id, OpportunityNoteCreate(body="Left voicemail about the quote")
            )

            detail = await service.get_opportunity(ws.id, opp.id)
            notes = [a for a in detail.activities if a.activity_type == "note"]
            assert len(notes) == 1
            assert notes[0].description == "Left voicemail about the quote"
            assert notes[0].opportunity_id == opp.id
            await db.rollback()

    async def test_update_kind_is_kept_distinct_from_a_note(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)

            await service.add_note(ws.id, opp.id, OpportunityNoteCreate(body="Note", kind="note"))
            await service.add_note(
                ws.id, opp.id, OpportunityNoteCreate(body="Roof measured", kind="update")
            )

            detail = await service.get_opportunity(ws.id, opp.id)
            kinds = sorted(a.activity_type for a in detail.activities)
            assert kinds == ["note", "update"]
            await db.rollback()

    async def test_note_is_trimmed(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)

            activity = await service.add_note(
                ws.id, opp.id, OpportunityNoteCreate(body="  spoke to Lisa  ")
            )

            assert activity.description == "spoke to Lisa"
            await db.rollback()

    async def test_empty_note_is_rejected_before_it_reaches_the_db(self) -> None:
        with pytest.raises(ValueError):
            OpportunityNoteCreate(body="")

    async def test_note_on_another_workspace_opportunity_is_not_found(self) -> None:
        async with AsyncSessionLocal() as db:
            mine = await _workspace(db)
            theirs = await _workspace(db)
            opp = await _opportunity(db, theirs.id)
            service = OpportunityService(db)

            with pytest.raises(Exception) as excinfo:
                await service.add_note(mine.id, opp.id, OpportunityNoteCreate(body="peek"))
            assert "404" in str(excinfo.value) or "not found" in str(excinfo.value).lower()
            await db.rollback()


class TestTasks:
    async def test_task_is_created_against_the_deal(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)

            due = datetime.now(UTC) + timedelta(days=2)
            task = await service.create_task(
                ws.id, opp.id, OpportunityTaskCreate(title="Send the quote", due_at=due)
            )

            assert task.opportunity_id == opp.id
            assert task.title == "Send the quote"
            assert task.completed_at is None
            await db.rollback()

    async def test_tasks_appear_on_the_detail_payload(self) -> None:
        """The sheet renders from the detail response, so it has to carry them."""
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)
            await service.create_task(ws.id, opp.id, OpportunityTaskCreate(title="Call back"))

            detail = await service.get_opportunity(ws.id, opp.id)

            assert [t.title for t in detail.tasks] == ["Call back"]
            await db.rollback()

    async def test_open_tasks_sort_before_completed_and_by_due_date(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)
            now = datetime.now(UTC)

            await service.create_task(ws.id, opp.id, OpportunityTaskCreate(title="undated"))
            await service.create_task(
                ws.id, opp.id, OpportunityTaskCreate(title="later", due_at=now + timedelta(days=5))
            )
            await service.create_task(
                ws.id, opp.id, OpportunityTaskCreate(title="sooner", due_at=now + timedelta(days=1))
            )
            done = await service.create_task(ws.id, opp.id, OpportunityTaskCreate(title="done"))
            await service.update_task(ws.id, opp.id, done.id, OpportunityTaskUpdate(completed=True))

            titles = [t.title for t in await service.list_tasks(ws.id, opp.id)]

            # Dated work first (soonest first), then undated, then anything done.
            assert titles == ["sooner", "later", "undated", "done"]
            await db.rollback()

    async def test_completing_a_task_stamps_who_and_when(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)
            task = await service.create_task(ws.id, opp.id, OpportunityTaskCreate(title="Call"))

            updated = await service.update_task(
                ws.id, opp.id, task.id, OpportunityTaskUpdate(completed=True)
            )

            assert updated.completed_at is not None
            await db.rollback()

    async def test_reopening_a_task_clears_completion(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)
            task = await service.create_task(ws.id, opp.id, OpportunityTaskCreate(title="Call"))
            await service.update_task(ws.id, opp.id, task.id, OpportunityTaskUpdate(completed=True))

            reopened = await service.update_task(
                ws.id, opp.id, task.id, OpportunityTaskUpdate(completed=False)
            )

            assert reopened.completed_at is None
            await db.rollback()

    async def test_completing_twice_keeps_the_first_timestamp(self) -> None:
        """Re-ticking a done box must not rewrite when the work happened."""
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)
            task = await service.create_task(ws.id, opp.id, OpportunityTaskCreate(title="Call"))
            first = await service.update_task(
                ws.id, opp.id, task.id, OpportunityTaskUpdate(completed=True)
            )
            stamp = first.completed_at

            again = await service.update_task(
                ws.id, opp.id, task.id, OpportunityTaskUpdate(completed=True)
            )

            assert again.completed_at == stamp
            await db.rollback()

    async def test_partial_update_leaves_other_fields_alone(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)
            due = datetime.now(UTC) + timedelta(days=3)
            task = await service.create_task(
                ws.id, opp.id, OpportunityTaskCreate(title="Send quote", due_at=due, notes="ping")
            )

            updated = await service.update_task(
                ws.id, opp.id, task.id, OpportunityTaskUpdate(completed=True)
            )

            assert updated.title == "Send quote"
            assert updated.notes == "ping"
            assert updated.due_at is not None
            await db.rollback()

    async def test_task_is_deleted(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp = await _opportunity(db, ws.id)
            service = OpportunityService(db)
            task = await service.create_task(ws.id, opp.id, OpportunityTaskCreate(title="Call"))

            await service.delete_task(ws.id, opp.id, task.id)

            assert await service.list_tasks(ws.id, opp.id) == []
            await db.rollback()

    async def test_tasks_do_not_leak_across_workspaces(self) -> None:
        async with AsyncSessionLocal() as db:
            mine = await _workspace(db)
            theirs = await _workspace(db)
            opp = await _opportunity(db, theirs.id)
            service = OpportunityService(db)
            await service.create_task(theirs.id, opp.id, OpportunityTaskCreate(title="secret"))

            with pytest.raises(Exception) as excinfo:
                await service.list_tasks(mine.id, opp.id)
            assert "404" in str(excinfo.value) or "not found" in str(excinfo.value).lower()
            await db.rollback()

    async def test_a_task_from_another_deal_cannot_be_patched(self) -> None:
        """The task id alone must not be enough -- it has to belong to the deal."""
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            opp_a = await _opportunity(db, ws.id)
            opp_b = await _opportunity(db, ws.id)
            service = OpportunityService(db)
            task = await service.create_task(ws.id, opp_a.id, OpportunityTaskCreate(title="A"))

            with pytest.raises(Exception) as excinfo:
                await service.update_task(
                    ws.id, opp_b.id, task.id, OpportunityTaskUpdate(completed=True)
                )
            assert "404" in str(excinfo.value) or "not found" in str(excinfo.value).lower()
            await db.rollback()
