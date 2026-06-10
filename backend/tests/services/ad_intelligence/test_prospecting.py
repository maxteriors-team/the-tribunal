"""Integration tests for advertiser -> LeadProspect generation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.ad_advertiser import AdAdvertiser, AdPlatform
from app.models.lead_prospect import LeadProspect
from app.models.workspace import Workspace
from app.services.ad_intelligence.prospecting import (
    generate_prospect_for_advertiser,
    generate_prospects_for_qualified,
)

NOW = datetime.now(UTC)


def _advertiser(workspace_id, *, key="100", host="acme.example", score=80, **kw) -> AdAdvertiser:
    base = {
        "workspace_id": workspace_id,
        "platform": AdPlatform.META,
        "advertiser_key": key,
        "page_id": key,
        "advertiser_name": "Acme Co",
        "page_url": f"https://www.facebook.com/{key}",
        "website_url": f"https://{host}" if host else None,
        "website_host": host,
        "country_code": "US",
        "opportunity_score": score,
        "continuity_score": 0.8,
        "longest_running_active_days": 180,
        "active_ad_count": 2,
        "distinct_creative_count": 2,
        "active_creative_count": 2,
        "creative_refresh_rate": 0.2,
        "reasons": ["Running the same creative for 180 days."],
        "example_creative": {
            "ad_external_id": "a1",
            "running_days": 180,
            "body_snippet": "Buy now",
        },
        "media_mix": {"video": 2},
    }
    base.update(kw)
    return AdAdvertiser(**base)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_generate_prospect_carries_ad_evidence() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Prosp", slug=f"prosp-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        adv = _advertiser(ws.id)
        db.add(adv)
        await db.flush()

        prospect = await generate_prospect_for_advertiser(db, adv)
        await db.flush()

        assert prospect.id is not None
        assert adv.prospect_id == prospect.id
        assert prospect.website_host == "acme.example"
        assert prospect.website_host_hash is not None
        assert prospect.source_type == "meta_ad_library"
        assert prospect.lead_score == 80
        # Ad-signal evidence carried, including the specific ad to reference.
        assert prospect.evidence
        signal = prospect.evidence[0]
        assert signal["type"] == "ad_signal"
        assert signal["example_creative"]["ad_external_id"] == "a1"
        assert signal["reasons"]

        # Idempotent: a second call returns the same prospect.
        again = await generate_prospect_for_advertiser(db, adv)
        assert again.id == prospect.id

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_qualified_filter_skips_prolific_testers() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Prosp2", slug=f"prosp-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()

        good = _advertiser(ws.id, key="good", host="good.example", score=85)
        # Prolific tester: many distinct creatives -> excluded by ICP.
        tester = _advertiser(
            ws.id,
            key="tester",
            host="tester.example",
            score=85,
            distinct_creative_count=40,
            active_creative_count=30,
            creative_refresh_rate=6.0,
        )
        db.add_all([good, tester])
        await db.flush()

        created = await generate_prospects_for_qualified(db, workspace_id=ws.id)
        await db.flush()

        keys = {
            (await db.get(AdAdvertiser, p_adv_id)).advertiser_key
            for p_adv_id in [good.id, tester.id]
        }
        assert keys == {"good", "tester"}
        # Only the good advertiser became a prospect.
        assert len(created) == 1
        prospects = (
            await db.execute(select(LeadProspect).where(LeadProspect.workspace_id == ws.id))
        ).scalars().all()
        assert len(prospects) == 1
        assert prospects[0].source_external_id == "good"

        await db.rollback()
