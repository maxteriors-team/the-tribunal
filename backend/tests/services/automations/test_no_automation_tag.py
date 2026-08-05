"""The ``no-automation`` tag is a per-customer kill switch.

Proves the two halves of the switch:

* every event-driven automation, because ``emit_automation_event`` is the one
  choke point all 16 triggers pass through; and
* the automatic quote-sent pipeline card, which is a direct service call and
  never reaches the event bus.

Manual operator actions are never blocked — this mutes automation, not the
human — which the last test pins.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.automation import Automation
from app.models.automation_event import AutomationEvent
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.workspace import Workspace
from app.services.automations.events import EVENT_QUOTE_SENT, emit_automation_event
from app.services.automations.opt_out import (
    NO_AUTOMATION_TAG,
    automation_suppressed,
)
from app.services.opportunities.quote_opportunity import place_quote_on_pipeline
from app.services.tags.tag_service import TagService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Each test owns its own connections; a pooled one belongs to a dead loop."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Muted", slug=f"muted-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1512555{uuid.uuid4().int % 10000:04d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Casey",
        phone_number=phone,
        phone_hash=hash_phone(phone),
    )
    db.add(contact)
    await db.flush()
    return contact


async def _listening_automation(db, workspace_id: uuid.UUID) -> Automation:
    automation = Automation(
        workspace_id=workspace_id,
        name="Quote sent follow-up",
        trigger_type=EVENT_QUOTE_SENT,
        is_active=True,
    )
    db.add(automation)
    await db.flush()
    return automation


async def _mute(db, contact: Contact, name: str = NO_AUTOMATION_TAG) -> None:
    await TagService(db).add_tag_to_contact(
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        name=name,
    )
    await db.flush()


async def _queued_events(db, workspace_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(AutomationEvent)
            .where(AutomationEvent.workspace_id == workspace_id)
        )
    ).scalar_one()


async def test_an_untagged_contact_still_queues_events() -> None:
    """Baseline: without the tag the event is queued as before."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _listening_automation(db, ws.id)

        event = await emit_automation_event(
            db,
            workspace_id=ws.id,
            event_type=EVENT_QUOTE_SENT,
            contact_id=contact.id,
        )
        await db.flush()

        assert event is not None
        assert await _queued_events(db, ws.id) == 1

        await db.rollback()


async def test_the_tag_stops_the_event_from_being_queued() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _listening_automation(db, ws.id)
        await _mute(db, contact)

        event = await emit_automation_event(
            db,
            workspace_id=ws.id,
            event_type=EVENT_QUOTE_SENT,
            contact_id=contact.id,
        )
        await db.flush()

        assert event is None
        assert await _queued_events(db, ws.id) == 0

        await db.rollback()


async def test_the_tag_is_matched_case_insensitively() -> None:
    """A hand-typed "No-Automation" must mute exactly like the UI's tag."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _mute(db, contact, name="No-Automation")

        assert await automation_suppressed(db, ws.id, contact.id) is True

        await db.rollback()


async def test_the_tag_only_mutes_the_contact_that_carries_it() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        muted = await _contact(db, ws.id)
        other = await _contact(db, ws.id)
        await _listening_automation(db, ws.id)
        await _mute(db, muted)

        assert await automation_suppressed(db, ws.id, muted.id) is True
        assert await automation_suppressed(db, ws.id, other.id) is False

        event = await emit_automation_event(
            db,
            workspace_id=ws.id,
            event_type=EVENT_QUOTE_SENT,
            contact_id=other.id,
        )
        assert event is not None

        await db.rollback()


async def test_a_workspace_level_event_is_never_suppressed() -> None:
    """No contact means no customer to have opted out."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)

        assert await automation_suppressed(db, ws.id, None) is False

        await db.rollback()


async def test_another_workspaces_tag_does_not_mute_this_one() -> None:
    """Tags are workspace-scoped; a same-named tag next door must not leak."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _mute(db, contact)

        assert await automation_suppressed(db, other.id, contact.id) is False

        await db.rollback()


async def test_the_tag_also_stops_the_quote_sent_pipeline_card() -> None:
    """The pipeline call bypasses the event bus, so it needs its own gate."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _mute(db, contact)

        card = await place_quote_on_pipeline(db, ws.id, contact)
        await db.flush()

        assert card is None
        count = (
            await db.execute(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.workspace_id == ws.id)
            )
        ).scalar_one()
        assert count == 0

        await db.rollback()


async def test_a_muted_contact_can_still_be_worked_by_hand() -> None:
    """Suppression covers automation only; the operator keeps every action."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _mute(db, contact)

        from app.services.opportunities.default_pipeline import (
            get_default_pipeline_first_stage,
        )

        pipeline, stage = await get_default_pipeline_first_stage(db, ws.id)
        manual = Opportunity(
            workspace_id=ws.id,
            pipeline_id=pipeline.id,
            stage_id=stage.id if stage else None,
            primary_contact_id=contact.id,
            name="Typed in by the owner",
            status="open",
        )
        db.add(manual)
        await db.flush()

        assert manual.id is not None
        # ...and the operator's own card is not swept away by the tag.
        still_there = (
            await db.execute(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.primary_contact_id == contact.id)
            )
        ).scalar_one()
        assert still_there == 1

        await db.rollback()
