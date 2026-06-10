"""Integration test for end-to-end ad-library discovery orchestration.

A fake provider returns a known result; the test asserts advertisers +
creatives are persisted, signals are computed onto the advertiser, and the job
transitions to ``succeeded`` with counters set.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.ad_advertiser import AdAdvertiser
from app.models.ad_creative import AdCreative
from app.models.lead_discovery_job import (
    DiscoveryJobStatus,
    DiscoverySourceType,
    LeadDiscoveryJob,
)
from app.models.workspace import Workspace
from app.services.ad_intelligence import discovery as discovery_mod
from app.services.ad_intelligence.types import (
    AdProviderResult,
    NormalizedAd,
    NormalizedAdvertiser,
)

NOW = datetime.now(UTC)


class _FakeProvider:
    def __init__(self, result: AdProviderResult) -> None:
        self._result = result
        self.closed = False

    async def search(self, request) -> AdProviderResult:  # noqa: ANN001
        return self._result

    async def close(self) -> None:
        self.closed = True


def _result() -> AdProviderResult:
    ads = (
        NormalizedAd(
            ad_external_id="a1",
            body="The same winning ad",
            link_caption="acme.example",
            link_url="https://acme.example",
            link_host="acme.example",
            media_type="video",
            platforms=("FACEBOOK",),
            ad_delivery_start_time=NOW - timedelta(days=200),
            is_active=True,
        ),
    )
    advertiser = NormalizedAdvertiser(
        platform="meta",
        advertiser_key="900900",
        page_id="900900",
        advertiser_name="Acme Co",
        website_url="https://acme.example",
        website_host="acme.example",
        country_code="US",
        ads=ads,
    )
    return AdProviderResult(
        platform="meta", advertisers=(advertiser,), requested_count=50, raw_ad_count=1
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_discovery_job_persists_and_scores(monkeypatch) -> None:
    fake = _FakeProvider(_result())

    async def _fake_build_provider(db, *, workspace_id, platform, use_thirdparty=False):  # noqa: ANN001
        return fake

    async def _allow(*args, **kwargs):  # noqa: ANN002, ANN003
        return True, 1

    monkeypatch.setattr(discovery_mod, "build_provider", _fake_build_provider)
    monkeypatch.setattr(discovery_mod, "acquire_provider_call_slot", _allow)

    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(), name="Disc Test", slug=f"disc-{uuid.uuid4().hex[:8]}"
        )
        db.add(workspace)
        await db.flush()

        job = LeadDiscoveryJob(
            workspace_id=workspace.id,
            source_type=DiscoverySourceType.META_AD_LIBRARY,
            status=DiscoveryJobStatus.PENDING,
            params={"search_terms": "roofing", "country": "US", "max_results": 50},
        )
        db.add(job)
        await db.flush()

        outcome = await discovery_mod.run_discovery_job(db, job)
        await db.flush()

        assert fake.closed is True
        assert outcome.advertiser_count == 1
        assert outcome.qualified_count == 1
        assert job.status == DiscoveryJobStatus.SUCCEEDED
        assert job.discovered_count == 1
        assert job.completed_at is not None

        advertiser = (
            await db.execute(
                select(AdAdvertiser).where(AdAdvertiser.workspace_id == workspace.id)
            )
        ).scalar_one()
        assert advertiser.advertiser_key == "900900"
        assert advertiser.longest_running_active_days == 200
        assert advertiser.opportunity_score >= 70
        assert advertiser.example_creative is not None
        assert advertiser.example_creative["ad_external_id"] == "a1"

        creatives = (
            await db.execute(
                select(AdCreative).where(AdCreative.advertiser_id == advertiser.id)
            )
        ).scalars().all()
        assert len(creatives) == 1

        await db.rollback()
