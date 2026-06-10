"""Integration tests for prospect -> contact promotion."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal
from app.models.contact import Contact
from app.models.lead_prospect import LeadProspect, ProspectStatus
from app.models.opt_out import GlobalOptOut
from app.models.tag import ContactTag
from app.models.workspace import Workspace
from app.services.outbound.promotion import ProspectPromotionService


def _prospect(workspace_id, *, phone="+15125550142", score=80, **kw) -> LeadProspect:
    base = {
        "workspace_id": workspace_id,
        "company_name": "Acme Co",
        "website_url": "https://acme.example",
        "website_host": "acme.example",
        "phone_number": phone,
        "phone_hash": hash_phone(phone) if phone else None,
        "source_type": "meta_ad_library",
        "dedupe_key": f"k-{uuid.uuid4().hex[:8]}",
        "lead_score": score,
        "status": ProspectStatus.ENRICHED,
        "evidence": [
            {
                "type": "ad_signal",
                "platform": "meta",
                "opportunity_score": score,
                "longest_running_active_days": 180,
                "distinct_creative_count": 2,
                "creative_refresh_rate": 0.2,
                "reasons": ["Running the same creative for 180 days."],
                "example_creative": {
                    "ad_external_id": "a1",
                    "running_days": 180,
                    "body_snippet": "Buy now",
                },
                "page_url": "https://facebook.com/100",
            }
        ],
    }
    base.update(kw)
    return LeadProspect(**base)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_promote_creates_contact_with_tags_and_intel() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Promo", slug=f"promo-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        prospect = _prospect(ws.id)
        db.add(prospect)
        await db.flush()

        service = ProspectPromotionService(db)
        result = await service.promote(prospect)
        await db.flush()

        assert result.promoted is True
        assert result.contact_id is not None
        assert prospect.contact_id == result.contact_id
        assert prospect.status == ProspectStatus.CONVERTED
        assert prospect.promoted_at is not None

        contact = await db.get(Contact, result.contact_id)
        assert contact.company_name == "Acme Co"
        assert contact.source == "ad_library"
        # Ad intel + the specific ad to reference carried into business_intel.
        ad_intel = contact.business_intel["ad_library"]
        assert ad_intel["example_creative"]["ad_external_id"] == "a1"
        assert ad_intel["opportunity_score"] == 80

        # Descriptive tags applied.
        tag_count = (
            await db.execute(
                select(func.count())
                .select_from(ContactTag)
                .where(ContactTag.contact_id == contact.id)
            )
        ).scalar_one()
        assert tag_count >= 3  # ad-library + long-runner + stale-creative + no-testing

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_promote_skips_no_phone() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Promo2", slug=f"promo-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        prospect = _prospect(ws.id, phone=None)
        db.add(prospect)
        await db.flush()

        result = await ProspectPromotionService(db).promote(prospect)
        assert result.promoted is False
        assert result.skipped_reason == "no_phone"
        assert prospect.contact_id is None

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_promote_respects_opt_out() -> None:
    phone = "+15125559999"
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Promo3", slug=f"promo-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        db.add(GlobalOptOut(workspace_id=ws.id, phone_number=phone))
        prospect = _prospect(ws.id, phone=phone)
        db.add(prospect)
        await db.flush()

        result = await ProspectPromotionService(db).promote(prospect)
        assert result.promoted is False
        assert result.skipped_reason == "opt_out"
        assert prospect.status == ProspectStatus.SUPPRESSED

        await db.rollback()
