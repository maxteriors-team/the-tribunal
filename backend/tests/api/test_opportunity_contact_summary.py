"""Integration tests for the primary-contact summary on opportunity payloads.

The pipeline board dials the lead straight from a card, so every opportunity
response has to carry that contact's name and phone. Both facts live on a
relationship, which makes this a test about *eager loading* as much as about
schema shape: a lazy load during async serialization raises ``MissingGreenlet``
and 500s the board, and no unit test with a mocked session can catch that.

Marked ``integration`` (run with ``-m integration``); each test opens an
``AsyncSessionLocal`` and rolls back on close, so the dev database stays clean.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.pipeline import Pipeline, PipelineStage
from app.models.workspace import Workspace
from app.services.opportunities import OpportunityService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Board", slug=f"bd-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _pipeline(db, workspace_id: uuid.UUID) -> tuple[Pipeline, PipelineStage]:
    pipeline = Pipeline(workspace_id=workspace_id, name="Sales")
    db.add(pipeline)
    await db.flush()
    stage = PipelineStage(pipeline_id=pipeline.id, name="New", order=0, probability=10)
    db.add(stage)
    await db.flush()
    return pipeline, stage


async def _contact(db, workspace_id: uuid.UUID, phone: str = "+15125550142") -> Contact:
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Helen",
        last_name="Vasquez",
        email="helen@example.com",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        status="qualified",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _opportunity(db, workspace_id, pipeline_id, stage_id, *, contact_id: int | None):
    opp = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline_id,
        stage_id=stage_id,
        name="Gutter clean",
        primary_contact_id=contact_id,
    )
    db.add(opp)
    await db.flush()
    return opp


async def test_list_embeds_the_primary_contact_for_click_to_call() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        pipeline, stage = await _pipeline(db, ws.id)
        contact = await _contact(db, ws.id)
        await _opportunity(db, ws.id, pipeline.id, stage.id, contact_id=contact.id)

        page = await OpportunityService(db).list_opportunities(ws.id, pipeline_id=pipeline.id)

        assert len(page.items) == 1
        summary = page.items[0].primary_contact
        assert summary is not None
        # The three fields the card cannot render without.
        assert summary.id == contact.id
        assert summary.full_name == "Helen Vasquez"
        assert summary.phone_number == "+15125550142"
        assert summary.status == "qualified"


async def test_list_leaves_primary_contact_null_when_none_is_linked() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        pipeline, stage = await _pipeline(db, ws.id)
        await _opportunity(db, ws.id, pipeline.id, stage.id, contact_id=None)

        page = await OpportunityService(db).list_opportunities(ws.id, pipeline_id=pipeline.id)

        assert len(page.items) == 1
        assert page.items[0].primary_contact is None


async def test_detail_embeds_the_primary_contact_too() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        pipeline, stage = await _pipeline(db, ws.id)
        contact = await _contact(db, ws.id, phone="+15125550188")
        opp = await _opportunity(db, ws.id, pipeline.id, stage.id, contact_id=contact.id)

        detail = await OpportunityService(db).get_opportunity(ws.id, opp.id)

        assert detail.primary_contact is not None
        assert detail.primary_contact.phone_number == "+15125550188"


async def test_list_can_narrow_to_one_contacts_deals() -> None:
    """The contact sidebar asks for one lead's cards, not the whole board.

    Without the filter the panel would render every deal in the workspace and
    an operator could not tell whether *this* lead is already in the pipeline.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        pipeline, stage = await _pipeline(db, ws.id)
        contact = await _contact(db, ws.id, phone="+15125550171")
        other = await _contact(db, ws.id, phone="+15125550172")
        mine = await _opportunity(db, ws.id, pipeline.id, stage.id, contact_id=contact.id)
        await _opportunity(db, ws.id, pipeline.id, stage.id, contact_id=other.id)
        await _opportunity(db, ws.id, pipeline.id, stage.id, contact_id=None)

        page = await OpportunityService(db).list_opportunities(ws.id, contact_id=contact.id)

        assert [item.id for item in page.items] == [mine.id]


async def test_summary_omits_contact_fields_the_board_has_no_use_for() -> None:
    """Guards the blast radius: this endpoint is not a contact export.

    Address, notes, lead scoring, and enrichment are PII the board never
    renders. If someone widens the summary, this fails and forces the question.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        pipeline, stage = await _pipeline(db, ws.id)
        contact = await _contact(db, ws.id, phone="+15125550199")
        contact.address_line1 = "18 Cedar Ln"
        contact.notes = "Haggled on price last time"
        await db.flush()
        await _opportunity(db, ws.id, pipeline.id, stage.id, contact_id=contact.id)

        page = await OpportunityService(db).list_opportunities(ws.id, pipeline_id=pipeline.id)
        payload = page.items[0].model_dump()

        assert set(payload["primary_contact"]) == {
            "id",
            "first_name",
            "last_name",
            "full_name",
            "phone_number",
            "email",
            "status",
        }
