"""A sent quote belongs on the sales board.

Pins the contract of :mod:`app.services.opportunities.quote_opportunity`:

* the flag is **on** by default (unlike ``auto_pipeline.enabled``), and off
  means nothing moves;
* a contact with an open deal has it advanced to ``Quote Sent / Follow Up``;
* a contact with no deal gets one opened there;
* a deal already at or past that stage is never dragged backwards;
* re-sending the same quote does nothing a second time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal
from app.models.contact import Contact
from app.models.opportunity import Opportunity, OpportunityActivity
from app.models.pipeline import PipelineStage
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.services.opportunities.default_pipeline import (
    QUOTE_SENT_STAGE_NAME,
    ensure_default_pipeline,
)
from app.services.opportunities.opportunity_service import OpportunityService
from app.services.opportunities.pipeline_removal import remove_from_pipeline
from app.services.opportunities.quote_opportunity import (
    mark_quote_approved_on_pipeline,
    on_quote_sent_enabled,
    place_quote_on_pipeline,
)

# ---------------------------------------------------------------------------
# Pure unit tests (no DB)
# ---------------------------------------------------------------------------


def test_quote_sent_pipeline_defaults_on() -> None:
    """Unlike inbound-lead auto-pipeline, this is on until switched off."""
    assert on_quote_sent_enabled(Workspace(settings={})) is True
    assert on_quote_sent_enabled(Workspace(settings=None)) is True  # type: ignore[arg-type]
    assert on_quote_sent_enabled(Workspace(settings={"auto_pipeline": {}})) is True


def test_quote_sent_pipeline_respects_an_explicit_off() -> None:
    off = Workspace(settings={"auto_pipeline": {"on_quote_sent": False}})
    on = Workspace(settings={"auto_pipeline": {"on_quote_sent": True}})
    assert on_quote_sent_enabled(off) is False
    assert on_quote_sent_enabled(on) is True


def test_quote_sent_pipeline_is_independent_of_the_inbound_lead_flag() -> None:
    """Leads stay opt-in while sent quotes stay opt-out; one flag is not the other."""
    leads_off = Workspace(settings={"auto_pipeline": {"enabled": False}})
    assert on_quote_sent_enabled(leads_off) is True


def test_quote_sent_pipeline_tolerates_malformed_settings() -> None:
    assert on_quote_sent_enabled(Workspace(settings={"auto_pipeline": "yes"})) is True


# ---------------------------------------------------------------------------
# Integration tests (real DB; run with `-m integration`)
# ---------------------------------------------------------------------------


async def _workspace(db, **settings: object) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="QuotePipe",
        slug=f"quotepipe-{uuid.uuid4().hex[:8]}",
        settings=dict(settings),
    )
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1512555{uuid.uuid4().int % 10000:04d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Quinn",
        last_name="Buyer",
        phone_number=phone,
        phone_hash=hash_phone(phone),
    )
    db.add(contact)
    await db.flush()
    return contact


async def _stage(db, pipeline_id: uuid.UUID, name: str) -> PipelineStage:
    return (
        await db.execute(
            select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == name,
            )
        )
    ).scalar_one()


async def _open_deal(db, workspace_id: uuid.UUID, contact: Contact, stage_name: str):
    pipeline = await ensure_default_pipeline(db, workspace_id)
    stage = await _stage(db, pipeline.id, stage_name)
    deal = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline.id,
        stage_id=stage.id,
        primary_contact_id=contact.id,
        name="Existing deal",
        probability=stage.probability,
        status="open",
    )
    db.add(deal)
    await db.flush()
    return deal, stage


@pytest.mark.integration
@pytest.mark.asyncio
async def test_first_send_opens_a_card_at_quote_sent() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)

        deal = await place_quote_on_pipeline(db, ws.id, contact, quote_id=uuid.uuid4())

        assert deal is not None
        stage = await _stage(db, deal.pipeline_id, QUOTE_SENT_STAGE_NAME)
        assert deal.stage_id == stage.id
        assert deal.probability == stage.probability
        assert deal.status == "open"
        assert deal.source == "quote_sent"

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_existing_open_deal_is_advanced_not_duplicated() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        existing, qualified = await _open_deal(db, ws.id, contact, "Qualified")

        moved = await place_quote_on_pipeline(db, ws.id, contact)
        await db.flush()

        assert moved is not None
        assert moved.id == existing.id
        target = await _stage(db, existing.pipeline_id, QUOTE_SENT_STAGE_NAME)
        assert existing.stage_id == target.id
        assert existing.probability == target.probability
        assert existing.stage_id != qualified.id

        # One card, and the move is on the record.
        count = (
            await db.execute(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.primary_contact_id == contact.id)
            )
        ).scalar_one()
        assert count == 1
        activities = (
            (
                await db.execute(
                    select(OpportunityActivity).where(
                        OpportunityActivity.opportunity_id == existing.id,
                        OpportunityActivity.activity_type == "stage_changed",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(activities) == 1
        assert activities[0].new_value == QUOTE_SENT_STAGE_NAME

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approved_quote_closes_and_values_its_linked_opportunity() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        opportunity = await place_quote_on_pipeline(db, ws.id, contact)
        assert opportunity is not None
        approved_at = datetime.now(UTC)
        quote = Quote(
            workspace_id=ws.id,
            contact_id=contact.id,
            opportunity_id=opportunity.id,
            number=f"QUO-{uuid.uuid4().hex[:8]}",
            status="approved",
            approved_at=approved_at,
            total=2_500,
            currency="USD",
        )
        db.add(quote)
        await db.flush()

        booked = await mark_quote_approved_on_pipeline(db, ws.id, quote)

        assert booked is not None
        assert booked.id == opportunity.id
        assert booked.status == "won"
        assert float(booked.amount) == 2_500
        assert booked.closed_date == approved_at.date()
        won_stage = await _stage(db, booked.pipeline_id, "Won")
        assert booked.stage_id == won_stage.id
        assert quote.opportunity_id == booked.id

        status_activity = (
            await db.execute(
                select(OpportunityActivity).where(
                    OpportunityActivity.opportunity_id == booked.id,
                    OpportunityActivity.activity_type == "status_changed",
                    OpportunityActivity.new_value == "won",
                )
            )
        ).scalar_one()
        assert quote.number in (status_activity.description or "")

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approval_creates_a_won_opportunity_when_none_exists() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        approved_at = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)
        quote = Quote(
            workspace_id=ws.id,
            contact_id=contact.id,
            number=f"Q-{uuid.uuid4().hex[:8]}",
            status="approved",
            currency="USD",
            total=875,
            approved_at=approved_at,
        )
        db.add(quote)
        await db.flush()

        booked = await mark_quote_approved_on_pipeline(db, ws.id, quote)

        assert booked is not None
        assert quote.opportunity_id == booked.id
        assert booked.status == "won"
        assert float(booked.amount) == 875
        won_stage = await _stage(db, booked.pipeline_id, "Won")
        assert booked.stage_id == won_stage.id
        assert booked.primary_contact_id == contact.id
        count = (
            await db.execute(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.primary_contact_id == contact.id)
            )
        ).scalar_one()
        assert count == 1

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resending_is_a_no_op() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)

        first = await place_quote_on_pipeline(db, ws.id, contact)
        await db.flush()
        second = await place_quote_on_pipeline(db, ws.id, contact)
        await db.flush()

        assert first is not None
        assert second is None  # already sitting in the quote-sent stage

        count = (
            await db.execute(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.primary_contact_id == contact.id)
            )
        ).scalar_one()
        assert count == 1

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_deal_further_along_is_never_dragged_backwards() -> None:
    """Quoting a deal that is already Won must not un-win it."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        existing, won_stage = await _open_deal(db, ws.id, contact, "Won")

        result = await place_quote_on_pipeline(db, ws.id, contact)

        assert result is None
        assert existing.stage_id == won_stage.id

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disabled_setting_leaves_the_board_alone() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, auto_pipeline={"on_quote_sent": False})
        contact = await _contact(db, ws.id)

        result = await place_quote_on_pipeline(db, ws.id, contact)

        assert result is None
        count = (
            await db.execute(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.workspace_id == ws.id)
            )
        ).scalar_one()
        assert count == 0

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_closed_deal_does_not_block_a_fresh_card() -> None:
    """A won job last season should not stop this season's quote appearing."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        closed, _ = await _open_deal(db, ws.id, contact, "Won")
        closed.status = "won"
        await db.flush()

        fresh = await place_quote_on_pipeline(db, ws.id, contact)
        await db.flush()

        assert fresh is not None
        assert fresh.id != closed.id
        target = await _stage(db, fresh.pipeline_id, QUOTE_SENT_STAGE_NAME)
        assert fresh.stage_id == target.id

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_removed_card_is_not_recreated_by_the_next_send() -> None:
    """Otherwise "Remove from pipeline" looks broken the moment you quote again."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)

        card = await place_quote_on_pipeline(db, ws.id, contact)
        assert card is not None
        await remove_from_pipeline(db, card)

        again = await place_quote_on_pipeline(db, ws.id, contact)
        await db.flush()

        assert again is None
        open_cards = (
            await db.execute(
                select(func.count())
                .select_from(Opportunity)
                .where(
                    Opportunity.primary_contact_id == contact.id,
                    Opportunity.status == "open",
                )
            )
        ).scalar_one()
        assert open_cards == 0

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_removal_keeps_the_card_and_its_history() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        card = await place_quote_on_pipeline(db, ws.id, contact)
        assert card is not None

        await remove_from_pipeline(db, card)

        assert card.status == "abandoned"
        assert card.is_active is False
        activity = (
            (
                await db.execute(
                    select(OpportunityActivity).where(
                        OpportunityActivity.opportunity_id == card.id,
                        OpportunityActivity.activity_type == "status_changed",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(activity) == 1
        assert activity[0].new_value == "abandoned"

        # Idempotent: removing twice does not log a second activity.
        await remove_from_pipeline(db, card)
        repeat = (
            await db.execute(
                select(func.count())
                .select_from(OpportunityActivity)
                .where(OpportunityActivity.opportunity_id == card.id)
            )
        ).scalar_one()
        assert repeat == 1

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_removed_card_is_omitted_from_pipeline_listing() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        removed, _ = await _open_deal(db, ws.id, contact, "Qualified")
        await remove_from_pipeline(db, removed)
        active, _ = await _open_deal(db, ws.id, contact, "Quote Sent / Follow Up")

        page = await OpportunityService(db).list_opportunities(
            ws.id, pipeline_id=active.pipeline_id
        )

        assert [opportunity.id for opportunity in page.items] == [active.id]
        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_operator_can_still_put_a_removed_contact_back_by_hand() -> None:
    """Removal suppresses *automation*, never the operator."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        card = await place_quote_on_pipeline(db, ws.id, contact)
        assert card is not None
        await remove_from_pipeline(db, card)

        manual, _stage_row = await _open_deal(db, ws.id, contact, "Qualified")

        assert manual.status == "open"
        # ...and a later quote send advances the deal they re-added.
        advanced = await place_quote_on_pipeline(db, ws.id, contact)
        assert advanced is not None
        assert advanced.id == manual.id

        await db.rollback()
