"""Integration test for the prospect enrichment worker.

Network calls (contact tracing + website enrichment) are monkeypatched so the
test asserts the wiring: traced email/phone land on the encrypted prospect
columns + hashes, the lead score is updated, audit rows are written, and the
prospect transitions new -> enriched.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.lead_prospect import (
    LeadEnrichmentResult,
    LeadProspect,
    ProspectStatus,
)
from app.models.workspace import Workspace
from app.services.ad_intelligence.contact_tracing import TracedContact
from app.workers import prospect_enrichment_worker as mod
from app.workers.prospect_enrichment_worker import ProspectEnrichmentWorker


class _FakeTracer:
    async def trace(self, *, website_url, website_host=None):  # noqa: ANN001
        return TracedContact(
            website_url=website_url,
            website_host=website_host,
            email="owner@acme.example",
            phone_number="+15125550142",
            linkedin_url="https://linkedin.com/company/acme",
            social_links={"linkedin": "https://linkedin.com/company/acme"},
            provenance={"traced": True},
        )

    async def close(self) -> None:
        return None


async def _fake_enrich(**kwargs):  # noqa: ANN003
    return {
        "business_intel": {"x": 1},
        "linkedin_url": "https://linkedin.com/company/acme",
        "lead_score": 95,
        "enrichment_status": "enriched",
        "error": None,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_enrich_sets_identifiers_and_audit(monkeypatch) -> None:
    monkeypatch.setattr(mod, "ContactTracer", lambda *a, **k: _FakeTracer())
    monkeypatch.setattr(mod, "enrich_contact_data", _fake_enrich)

    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Enrich", slug=f"enrich-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()

        prospect = LeadProspect(
            workspace_id=ws.id,
            company_name="Acme Co",
            website_url="https://acme.example",
            website_host="acme.example",
            source_type="meta_ad_library",
            dedupe_key=f"k-{uuid.uuid4().hex[:8]}",
            lead_score=40,
            status=ProspectStatus.NEW,
        )
        db.add(prospect)
        await db.flush()

        worker = ProspectEnrichmentWorker()
        await worker._enrich(db, prospect)
        await db.flush()

        assert prospect.status == ProspectStatus.ENRICHED
        assert prospect.has_email is True
        assert prospect.has_phone is True
        assert prospect.email_hash is not None
        assert prospect.phone_hash is not None
        assert prospect.linkedin_url == "https://linkedin.com/company/acme"
        # Website enrichment raised the score from 40 -> 95.
        assert prospect.lead_score == 95
        assert prospect.last_enriched_at is not None

        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(LeadEnrichmentResult)
                .where(LeadEnrichmentResult.prospect_id == prospect.id)
            )
        ).scalar_one()
        # contact-trace + website-scraper audit rows at minimum.
        assert audit_count >= 2

        await db.rollback()
