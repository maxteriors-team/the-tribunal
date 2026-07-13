"""Tests for auto-pipeline lead-opportunity creation.

Proves the "new leads automatically go into the pipeline" contract:

* A new lead lands on the board in the default pipeline's first stage.
* A contact never gets two open cards (idempotent per contact).
* The workspace ``auto_pipeline.enabled`` setting gates the behavior.
* A closed (won/lost) deal does not block a returning lead's fresh card.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.pipeline import PipelineStage
from app.models.workspace import Workspace
from app.services.opportunities import open_lead_opportunity
from app.services.opportunities.lead_opportunity import (
    _opportunity_name,
    auto_pipeline_enabled,
)

# ---------------------------------------------------------------------------
# Pure unit tests (no DB)
# ---------------------------------------------------------------------------


def _contact(**kw: object) -> Contact:
    base: dict[str, object] = {"first_name": "Jane", "last_name": None, "company_name": None}
    base.update(kw)
    return Contact(**base)  # type: ignore[arg-type]


def test_auto_pipeline_enabled_defaults_on() -> None:
    assert auto_pipeline_enabled(Workspace(settings={})) is True
    assert auto_pipeline_enabled(Workspace(settings=None)) is True  # type: ignore[arg-type]
    assert auto_pipeline_enabled(Workspace(settings={"auto_pipeline": {}})) is True


def test_auto_pipeline_enabled_respects_explicit_flag() -> None:
    off = Workspace(settings={"auto_pipeline": {"enabled": False}})
    on = Workspace(settings={"auto_pipeline": {"enabled": True}})
    assert auto_pipeline_enabled(off) is False
    assert auto_pipeline_enabled(on) is True


def test_auto_pipeline_enabled_tolerates_malformed_settings() -> None:
    assert auto_pipeline_enabled(Workspace(settings={"auto_pipeline": "yes"})) is True


def test_opportunity_name_variants() -> None:
    assert _opportunity_name(_contact(first_name="Jane", last_name="Doe")) == "Jane Doe"
    assert (
        _opportunity_name(_contact(first_name="Jane", last_name="Doe", company_name="Acme"))
        == "Jane Doe — Acme"
    )
    assert _opportunity_name(_contact(first_name="", company_name="Acme")) == "Acme"
    assert _opportunity_name(_contact(first_name="")) == "New lead"


# ---------------------------------------------------------------------------
# Integration tests (real DB; run with `-m integration`)
# ---------------------------------------------------------------------------

pytestmark_integration = [pytest.mark.asyncio, pytest.mark.integration]


def _persisted_contact(workspace_id: uuid.UUID, *, phone: str | None = None) -> Contact:
    phone = phone or f"+1512555{uuid.uuid4().int % 10000:04d}"
    return Contact(
        workspace_id=workspace_id,
        first_name="Jane",
        last_name="Lead",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        status="new",
    )


async def _new_workspace(db: object, **settings: object) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="AutoPipe",
        slug=f"autopipe-{uuid.uuid4().hex[:8]}",
        settings=dict(settings),
    )
    db.add(ws)  # type: ignore[attr-defined]
    await db.flush()  # type: ignore[attr-defined]
    return ws


@pytest.mark.integration
@pytest.mark.asyncio
async def test_new_lead_lands_in_first_stage() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _new_workspace(db)
        contact = _persisted_contact(ws.id)
        db.add(contact)
        await db.flush()

        opp = await open_lead_opportunity(db, ws.id, contact, source="lead_form")
        await db.flush()

        assert opp is not None
        assert opp.primary_contact_id == contact.id
        assert opp.status == "open"
        assert opp.source == "lead_form"

        # The card is in the default pipeline's entry stage (order 0 = "New").
        first_stage = (
            await db.execute(
                select(PipelineStage)
                .where(PipelineStage.pipeline_id == opp.pipeline_id)
                .order_by(PipelineStage.order.asc())
                .limit(1)
            )
        ).scalar_one()
        assert opp.stage_id == first_stage.id
        assert first_stage.order == 0
        assert opp.probability == first_stage.probability

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_never_creates_two_open_cards_for_one_contact() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _new_workspace(db)
        contact = _persisted_contact(ws.id)
        db.add(contact)
        await db.flush()

        first = await open_lead_opportunity(db, ws.id, contact, source="lead_form")
        await db.flush()
        second = await open_lead_opportunity(db, ws.id, contact, source="inbound_sms")
        await db.flush()

        assert first is not None
        assert second is None  # deduped: already has an open card

        count = (
            await db.execute(
                select(func.count())
                .select_from(Opportunity)
                .where(
                    Opportunity.workspace_id == ws.id,
                    Opportunity.primary_contact_id == contact.id,
                )
            )
        ).scalar_one()
        assert count == 1

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disabled_setting_skips_card() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _new_workspace(db, auto_pipeline={"enabled": False})
        contact = _persisted_contact(ws.id)
        db.add(contact)
        await db.flush()

        opp = await open_lead_opportunity(db, ws.id, contact, source="lead_form")
        await db.flush()

        assert opp is None
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
async def test_closed_deal_does_not_block_new_card() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _new_workspace(db)
        contact = _persisted_contact(ws.id)
        db.add(contact)
        await db.flush()

        first = await open_lead_opportunity(db, ws.id, contact, source="lead_form")
        await db.flush()
        assert first is not None

        # The lead's first deal closes; a later touch should open a fresh card.
        first.status = "won"
        await db.flush()

        second = await open_lead_opportunity(db, ws.id, contact, source="inbound_call")
        await db.flush()
        assert second is not None
        assert second.id != first.id

        open_count = (
            await db.execute(
                select(func.count())
                .select_from(Opportunity)
                .where(
                    Opportunity.workspace_id == ws.id,
                    Opportunity.primary_contact_id == contact.id,
                    Opportunity.status == "open",
                )
            )
        ).scalar_one()
        assert open_count == 1

        await db.rollback()
