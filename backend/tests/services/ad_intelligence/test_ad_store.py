"""Tests for the ad-library upsert store.

Pure-function coverage for the creative fingerprint always runs. A DB-backed
idempotency test (marked ``integration``) asserts re-running a scan updates the
same advertiser/creative rows rather than duplicating them, and that active
transitions + first/last-seen tracking behave across runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.ad_advertiser import AdAdvertiser
from app.models.ad_creative import AdCreative
from app.models.workspace import Workspace
from app.services.ad_intelligence.ad_store import AdStore, normalize_creative_hash
from app.services.ad_intelligence.types import (
    AdProviderResult,
    NormalizedAd,
    NormalizedAdvertiser,
)

NOW = datetime.now(UTC)
FUTURE = NOW + timedelta(days=30)
PAST = NOW - timedelta(days=5)


def _ad(
    ad_id: str, *, body: str, host: str = "acme.example", stop=None, active=True
) -> NormalizedAd:
    return NormalizedAd(
        ad_external_id=ad_id,
        body=body,
        link_caption=host,
        link_url=f"https://{host}",
        link_host=host,
        media_type="video",
        platforms=("FACEBOOK",),
        ad_delivery_start_time=NOW - timedelta(days=100),
        ad_delivery_stop_time=stop,
        is_active=active,
    )


def _result(*ads: NormalizedAd, key: str = "100") -> AdProviderResult:
    advertiser = NormalizedAdvertiser(
        platform="meta",
        advertiser_key=key,
        page_id=key,
        advertiser_name="Acme Co",
        website_url="https://acme.example",
        website_host="acme.example",
        country_code="US",
        ads=tuple(ads),
    )
    return AdProviderResult(
        platform="meta", advertisers=(advertiser,), requested_count=50, raw_ad_count=len(ads)
    )


def test_creative_hash_is_stable_and_distinct() -> None:
    a = _ad("1", body="Buy now")
    b = _ad("2", body="Buy now")  # same content, different ad id
    c = _ad("3", body="Totally different copy")
    # Same content => same fingerprint (collapses to one distinct creative).
    assert normalize_creative_hash(a) == normalize_creative_hash(b)
    assert normalize_creative_hash(a) != normalize_creative_hash(c)


def test_creative_hash_ignores_whitespace_and_case() -> None:
    a = _ad("1", body="Hello   World")
    b = _ad("2", body="hello world")
    assert normalize_creative_hash(a) == normalize_creative_hash(b)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_is_idempotent_and_tracks_transitions() -> None:
    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(), name="AdStore Test", slug=f"adstore-{uuid.uuid4().hex[:8]}"
        )
        db.add(workspace)
        await db.flush()

        store = AdStore(db)

        # First scan: two ads, both active.
        await store.upsert_result(
            workspace_id=workspace.id,
            result=_result(
                _ad("1", body="Long runner", active=True),
                _ad("2", body="Second creative", active=True),
            ),
            scanned_at=NOW - timedelta(days=10),
        )

        # Second scan: ad 2 has now stopped; ad 1 still active; new ad 3 appears.
        advertisers = await store.upsert_result(
            workspace_id=workspace.id,
            result=_result(
                _ad("1", body="Long runner", active=True),
                _ad("2", body="Second creative", stop=PAST, active=False),
                _ad("3", body="Fresh creative", active=True),
            ),
            scanned_at=NOW,
        )
        await db.flush()

        assert len(advertisers) == 1
        advertiser = advertisers[0]

        # Only one advertiser row exists (idempotent on the unique key).
        adv_rows = (
            await db.execute(
                select(AdAdvertiser).where(AdAdvertiser.workspace_id == workspace.id)
            )
        ).scalars().all()
        assert len(adv_rows) == 1

        # Three creatives total (ads 1, 2, 3) — no duplicates for re-seen ads.
        creatives = (
            await db.execute(
                select(AdCreative).where(AdCreative.advertiser_id == advertiser.id)
            )
        ).scalars().all()
        assert len(creatives) == 3
        by_id = {c.ad_external_id: c for c in creatives}
        assert by_id["1"].is_active is True
        assert by_id["2"].is_active is False  # transitioned to inactive
        assert by_id["2"].ad_delivery_stop_time is not None
        # first_seen preserved from the first scan; last_seen advanced.
        assert by_id["1"].last_seen_at == NOW
        assert advertiser.last_scanned_at == NOW

        await db.rollback()
