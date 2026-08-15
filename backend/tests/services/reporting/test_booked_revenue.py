"""Canonical booked-revenue ledger integration tests."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.pipeline import PipelineStage
from app.models.quote import Quote
from app.models.referral_partner import ReferralPartner
from app.models.workspace import Workspace
from app.services.lead_sources.referral_partner_service import ReferralPartnerService
from app.services.opportunities.default_pipeline import ensure_default_pipeline
from app.services.reporting.booked_revenue import get_booked_revenue_totals


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Keep shared asyncpg connections on each test's event loop."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _contact(db, workspace_id: uuid.UUID, suffix: int) -> Contact:
    phone = f"+1512555{suffix:04d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Booked",
        last_name=f"Customer {suffix}",
        phone_number=phone,
        phone_hash=hash_phone(phone),
    )
    db.add(contact)
    await db.flush()
    return contact


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quote_backed_wins_are_counted_once_with_unquoted_legacy_wins() -> None:
    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(),
            name="Booked Revenue Test",
            slug=f"booked-revenue-{uuid.uuid4().hex[:8]}",
            settings={"timezone": "America/Chicago"},
        )
        db.add(workspace)
        await db.flush()
        pipeline = await ensure_default_pipeline(db, workspace.id)
        open_stage = (
            await db.execute(
                select(PipelineStage)
                .where(PipelineStage.pipeline_id == pipeline.id)
                .order_by(PipelineStage.order.asc())
                .limit(1)
            )
        ).scalar_one()

        partner = ReferralPartner(workspace_id=workspace.id, name="Canonical partner")
        db.add(partner)
        await db.flush()

        quote_contact = await _contact(db, workspace.id, 6101)
        legacy_contact = await _contact(db, workspace.id, 6102)
        direct_quote_contact = await _contact(db, workspace.id, 6103)
        quote_contact.referral_partner_id = partner.id
        legacy_contact.referral_partner_id = partner.id
        direct_quote_contact.referral_partner_id = partner.id

        quote_backed = Opportunity(
            workspace_id=workspace.id,
            pipeline_id=pipeline.id,
            stage_id=open_stage.id,
            primary_contact_id=quote_contact.id,
            name="Quote-backed win",
            status="won",
            amount=1_000,
            closed_date=date(2026, 8, 10),
        )
        legacy = Opportunity(
            workspace_id=workspace.id,
            pipeline_id=pipeline.id,
            stage_id=open_stage.id,
            primary_contact_id=legacy_contact.id,
            name="Legacy manual win",
            status="won",
            amount=700,
            closed_date=date(2026, 8, 11),
        )
        db.add_all([quote_backed, legacy])
        await db.flush()

        db.add_all(
            [
                Quote(
                    workspace_id=workspace.id,
                    contact_id=quote_contact.id,
                    opportunity_id=quote_backed.id,
                    number=f"QUO-{uuid.uuid4().hex[:8]}",
                    status="approved",
                    approved_at=datetime(2026, 8, 10, 15, tzinfo=UTC),
                    total=1_200,
                    currency="USD",
                ),
                Quote(
                    workspace_id=workspace.id,
                    contact_id=direct_quote_contact.id,
                    number=f"QUO-{uuid.uuid4().hex[:8]}",
                    status="approved",
                    approved_at=datetime(2026, 8, 12, 15, tzinfo=UTC),
                    total=300,
                    currency="USD",
                ),
            ]
        )
        await db.flush()

        totals = await get_booked_revenue_totals(
            db,
            workspace.id,
            date(2026, 8, 1),
            date(2026, 8, 31),
            timezone_name="America/Chicago",
        )

        assert totals.count == 3
        assert float(totals.revenue) == 2_200

        scoreboard = await ReferralPartnerService(db).scoreboard(workspace.id)
        assert scoreboard.total_jobs_closed == 3
        assert scoreboard.total_revenue == 2_200
        assert scoreboard.items[0].partner_id == partner.id
        assert scoreboard.items[0].close_rate == 1.0

        await db.rollback()
