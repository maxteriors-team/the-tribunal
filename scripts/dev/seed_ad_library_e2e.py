"""Seed deterministic Ad Library data for manual end-to-end QA.

Run from the backend dir so app imports resolve:

    cd backend && uv run python ../scripts/dev/seed_ad_library_e2e.py <workspace_id>

Idempotent: removes any prior ``e2e-seed-*`` advertisers (and their cascaded
creatives) for the workspace, plus the seeded prospect, then re-inserts a fixed
set of advertisers with varied signals so the ranked list + ICP filter + detail
view all have something to click through.

Advertisers (deterministic UUIDs via uuid5):
  1. Evergreen Roofing Co     — top ICP fit, contact_traced + linked LeadProspect
  2. Lakeside Family Dental   — qualified
  3. Summit Air & Heating     — qualified (near floors)
  4. Bargain Bin Outlet       — NOT qualified (opportunity_score < 50)
  5. Viral UGC Labs           — prolific tester, 40 distinct creatives (ICP hides)
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal
from app.models.ad_advertiser import AdAdvertiser, AdPlatform
from app.models.ad_creative import AdCreative, AdMediaType
from app.models.lead_prospect import (
    LeadProspect,
    ProspectIdentityKind,
    ProspectStatus,
)

NS = uuid.UUID("00000000-0000-0000-0000-00000000ad11")  # stable seed namespace
NOW = datetime.now(UTC)


def adv_id(key: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"advertiser:{key}")


def creative_id(adv_key: str, n: int) -> uuid.UUID:
    return uuid.uuid5(NS, f"creative:{adv_key}:{n}")


def prospect_id() -> uuid.UUID:
    return uuid.uuid5(NS, "prospect:evergreen-roofing")


def _started(days_ago: int) -> datetime:
    return NOW - timedelta(days=days_ago)


def make_creative(
    *,
    workspace_id: uuid.UUID,
    advertiser_id: uuid.UUID,
    adv_key: str,
    n: int,
    body: str,
    title: str,
    link_caption: str,
    link_host: str,
    media: AdMediaType,
    running_days: int,
    is_active: bool = True,
) -> AdCreative:
    start = _started(running_days)
    return AdCreative(
        id=creative_id(adv_key, n),
        workspace_id=workspace_id,
        advertiser_id=advertiser_id,
        ad_external_id=f"{adv_key}-ad-{n}",
        creative_hash=uuid.uuid5(NS, f"hash:{adv_key}:{n}").hex[:32],
        body=body,
        title=title,
        link_caption=link_caption,
        link_url=f"https://{link_host}/lp/{n}",
        link_host=link_host,
        cta_type="LEARN_MORE",
        snapshot_url=f"https://www.facebook.com/ads/library/?id={adv_key}-ad-{n}",
        media_type=media,
        platforms=["facebook", "instagram"],
        ad_delivery_start_time=start,
        ad_delivery_stop_time=None if is_active else _started(running_days - 5),
        is_active=is_active,
        first_seen_at=start,
        last_seen_at=NOW,
    )


def example_creative_blob(
    *, adv_key: str, n: int, body: str, link_caption: str, link_host: str,
    media: str, running_days: int,
) -> dict:
    snippet = body[:160] + ("…" if len(body) > 160 else "")
    return {
        "ad_external_id": f"{adv_key}-ad-{n}",
        "body_snippet": snippet,
        "link_caption": link_caption,
        "link_url": f"https://{link_host}/lp/{n}",
        "snapshot_url": f"https://www.facebook.com/ads/library/?id={adv_key}-ad-{n}",
        "media_type": media,
        "running_days": running_days,
        "delivery_start_time": _started(running_days).isoformat(),
    }


async def seed(workspace_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        # --- Clean prior seed rows (idempotent) -----------------------------
        seed_keys = [
            "e2e-seed-evergreen-roofing",
            "e2e-seed-lakeside-dental",
            "e2e-seed-summit-hvac",
            "e2e-seed-bargain-bin",
            "e2e-seed-viral-ugc-labs",
        ]
        existing = (
            await db.execute(
                select(AdAdvertiser.id).where(
                    AdAdvertiser.workspace_id == workspace_id,
                    AdAdvertiser.advertiser_key.in_(seed_keys),
                )
            )
        ).scalars().all()
        if existing:
            await db.execute(
                delete(AdAdvertiser).where(AdAdvertiser.id.in_(existing))
            )
        await db.execute(
            delete(LeadProspect).where(LeadProspect.id == prospect_id())
        )
        await db.flush()

        # --- Linked prospect for advertiser #1 (contact_traced) -------------
        prospect = LeadProspect(
            id=prospect_id(),
            workspace_id=workspace_id,
            identity_kind=ProspectIdentityKind.MULTI,
            full_name="Dana Reyes",
            first_name="Dana",
            last_name="Reyes",
            email="owner@evergreenroofingco.com",
            email_hash=hash_value("owner@evergreenroofingco.com"),
            phone_number="+15125550142",
            phone_hash=hash_value("+15125550142"),
            company_name="Evergreen Roofing Co",
            website_url="https://evergreenroofingco.com",
            website_host="evergreenroofingco.com",
            linkedin_url="https://www.linkedin.com/company/evergreen-roofing-co",
            country_code="US",
            region="TX",
            city="Austin",
            location_label="Austin, TX",
            source_type="ad_library",
            source_external_id="e2e-seed-evergreen-roofing",
            status=ProspectStatus.ENRICHED,
            lead_score=88,
            qualification_score=80,
            last_enriched_at=NOW,
        )
        db.add(prospect)
        await db.flush()

        advertisers: list[AdAdvertiser] = []

        # 1) Top ICP fit + contact_traced + linked prospect ------------------
        a1_key = "e2e-seed-evergreen-roofing"
        a1 = AdAdvertiser(
            id=adv_id(a1_key),
            workspace_id=workspace_id,
            prospect_id=prospect.id,
            platform=AdPlatform.META,
            advertiser_key=a1_key,
            page_id="100000000000001",
            advertiser_name="Evergreen Roofing Co",
            page_url="https://www.facebook.com/evergreenroofingco",
            website_url="https://evergreenroofingco.com",
            website_host="evergreenroofingco.com",
            country_code="US",
            first_seen_at=_started(300),
            last_seen_at=NOW,
            last_scanned_at=NOW,
            is_active=True,
            signal_window_days=365,
            total_ad_count=3,
            active_ad_count=3,
            distinct_creative_count=3,
            active_creative_count=3,
            longest_running_active_days=280,
            creative_refresh_rate=0.3,
            continuity_score=0.96,
            opportunity_score=92,
            platform_spread=["facebook", "instagram"],
            media_mix={"image": 2, "video": 1},
            reasons=[
                "longest-run 280d — same hero ad all year",
                "only 3 distinct creatives — never iterates",
                "continuity 0.96 — spends every week",
            ],
            signals={"recommendation": "ideal_consistent_non_tester"},
            example_creative=example_creative_blob(
                adv_key=a1_key, n=1, media="image", running_days=280,
                link_caption="evergreenroofingco.com",
                link_host="evergreenroofingco.com",
                body="Free roof inspection this spring — trusted by 2,000+ Austin homeowners since 2009.",
            ),
            contact_traced=True,
        )
        a1.creatives = [
            make_creative(workspace_id=workspace_id, advertiser_id=a1.id, adv_key=a1_key, n=1,
                          body="Free roof inspection this spring — trusted by 2,000+ Austin homeowners since 2009.",
                          title="Free Roof Inspection", link_caption="evergreenroofingco.com",
                          link_host="evergreenroofingco.com", media=AdMediaType.IMAGE, running_days=280),
            make_creative(workspace_id=workspace_id, advertiser_id=a1.id, adv_key=a1_key, n=2,
                          body="Storm damage? We handle the insurance paperwork for you.",
                          title="Storm Damage Repair", link_caption="evergreenroofingco.com",
                          link_host="evergreenroofingco.com", media=AdMediaType.VIDEO, running_days=190),
            make_creative(workspace_id=workspace_id, advertiser_id=a1.id, adv_key=a1_key, n=3,
                          body="Metal roofs that last 50 years. Financing available.",
                          title="Metal Roofing", link_caption="evergreenroofingco.com",
                          link_host="evergreenroofingco.com", media=AdMediaType.IMAGE, running_days=120),
        ]
        advertisers.append(a1)

        # 2) Qualified, no trace ---------------------------------------------
        a2_key = "e2e-seed-lakeside-dental"
        a2 = AdAdvertiser(
            id=adv_id(a2_key), workspace_id=workspace_id, platform=AdPlatform.META,
            advertiser_key=a2_key, page_id="100000000000002",
            advertiser_name="Lakeside Family Dental",
            page_url="https://www.facebook.com/lakesidefamilydental",
            website_url="https://lakesidefamilydental.com", website_host="lakesidefamilydental.com",
            country_code="US", first_seen_at=_started(160), last_seen_at=NOW, last_scanned_at=NOW,
            is_active=True, signal_window_days=365, total_ad_count=5, active_ad_count=4,
            distinct_creative_count=5, active_creative_count=5, longest_running_active_days=140,
            creative_refresh_rate=0.8, continuity_score=0.82, opportunity_score=78,
            platform_spread=["facebook", "instagram"], media_mix={"image": 4, "video": 1},
            reasons=["longest-run 140d", "5 distinct creatives — light iteration", "continuity 0.82"],
            signals={"recommendation": "consistent_non_tester"},
            example_creative=example_creative_blob(
                adv_key=a2_key, n=1, media="image", running_days=140,
                link_caption="lakesidefamilydental.com", link_host="lakesidefamilydental.com",
                body="New patient special: $99 cleaning, exam & X-rays. Accepting new families.",
            ),
            contact_traced=False,
        )
        a2.creatives = [
            make_creative(workspace_id=workspace_id, advertiser_id=a2.id, adv_key=a2_key, n=i,
                          body=f"New patient special #{i}: $99 cleaning, exam & X-rays.",
                          title="New Patient Special", link_caption="lakesidefamilydental.com",
                          link_host="lakesidefamilydental.com", media=AdMediaType.IMAGE,
                          running_days=140 - i * 12)
            for i in range(1, 6)
        ]
        advertisers.append(a2)

        # 3) Qualified, near the floors --------------------------------------
        a3_key = "e2e-seed-summit-hvac"
        a3 = AdAdvertiser(
            id=adv_id(a3_key), workspace_id=workspace_id, platform=AdPlatform.META,
            advertiser_key=a3_key, page_id="100000000000003",
            advertiser_name="Summit Air & Heating",
            page_url="https://www.facebook.com/summitairheating",
            website_url="https://summitairheating.com", website_host="summitairheating.com",
            country_code="US", first_seen_at=_started(110), last_seen_at=NOW, last_scanned_at=NOW,
            is_active=True, signal_window_days=365, total_ad_count=6, active_ad_count=2,
            distinct_creative_count=6, active_creative_count=6, longest_running_active_days=95,
            creative_refresh_rate=1.2, continuity_score=0.61, opportunity_score=64,
            platform_spread=["facebook"], media_mix={"image": 5, "video": 1},
            reasons=["longest-run 95d", "continuity 0.61 — meets floor", "6 distinct creatives"],
            signals={"recommendation": "consistent_non_tester"},
            example_creative=example_creative_blob(
                adv_key=a3_key, n=1, media="image", running_days=95,
                link_caption="summitairheating.com", link_host="summitairheating.com",
                body="AC tune-up $79. Beat the summer rush — book your maintenance today.",
            ),
            contact_traced=False,
        )
        a3.creatives = [
            make_creative(workspace_id=workspace_id, advertiser_id=a3.id, adv_key=a3_key, n=i,
                          body=f"AC tune-up offer #{i}. Beat the summer rush.",
                          title="AC Tune-Up", link_caption="summitairheating.com",
                          link_host="summitairheating.com", media=AdMediaType.IMAGE,
                          running_days=95 - i * 10, is_active=i <= 2)
            for i in range(1, 7)
        ]
        advertisers.append(a3)

        # 4) NOT qualified — opportunity_score below the 50 floor -------------
        a4_key = "e2e-seed-bargain-bin"
        a4 = AdAdvertiser(
            id=adv_id(a4_key), workspace_id=workspace_id, platform=AdPlatform.META,
            advertiser_key=a4_key, page_id="100000000000004",
            advertiser_name="Bargain Bin Outlet",
            page_url="https://www.facebook.com/bargainbinoutlet",
            website_url="https://bargainbinoutlet.com", website_host="bargainbinoutlet.com",
            country_code="US", first_seen_at=_started(80), last_seen_at=NOW, last_scanned_at=NOW,
            is_active=True, signal_window_days=365, total_ad_count=4, active_ad_count=1,
            distinct_creative_count=4, active_creative_count=2, longest_running_active_days=70,
            creative_refresh_rate=1.0, continuity_score=0.55, opportunity_score=41,
            platform_spread=["facebook"], media_mix={"image": 4},
            reasons=["score 41 (< 50) — weak overall fit", "intermittent delivery"],
            signals={"recommendation": "below_threshold"},
            example_creative=example_creative_blob(
                adv_key=a4_key, n=1, media="image", running_days=70,
                link_caption="bargainbinoutlet.com", link_host="bargainbinoutlet.com",
                body="Clearance blowout — up to 70% off everything in store.",
            ),
            contact_traced=False,
        )
        a4.creatives = [
            make_creative(workspace_id=workspace_id, advertiser_id=a4.id, adv_key=a4_key, n=i,
                          body=f"Clearance blowout #{i} — up to 70% off.",
                          title="Clearance", link_caption="bargainbinoutlet.com",
                          link_host="bargainbinoutlet.com", media=AdMediaType.IMAGE,
                          running_days=70 - i * 12, is_active=i == 1)
            for i in range(1, 5)
        ]
        advertisers.append(a4)

        # 5) Prolific tester — 40 distinct creatives (ICP excludes) ----------
        a5_key = "e2e-seed-viral-ugc-labs"
        a5 = AdAdvertiser(
            id=adv_id(a5_key), workspace_id=workspace_id, platform=AdPlatform.META,
            advertiser_key=a5_key, page_id="100000000000005",
            advertiser_name="Viral UGC Labs",
            page_url="https://www.facebook.com/viralugclabs",
            website_url="https://viralugclabs.com", website_host="viralugclabs.com",
            country_code="US", first_seen_at=_started(200), last_seen_at=NOW, last_scanned_at=NOW,
            is_active=True, signal_window_days=365, total_ad_count=40, active_ad_count=38,
            distinct_creative_count=40, active_creative_count=38, longest_running_active_days=120,
            creative_refresh_rate=9.5, continuity_score=0.94, opportunity_score=71,
            platform_spread=["facebook", "instagram", "tiktok"],
            media_mix={"video": 34, "image": 6},
            reasons=[
                "40 distinct creatives (> 8) — already testing at scale",
                "refresh 9.5/30d (> 4.0) — iterating constantly",
                "high opportunity score but excluded as a prolific tester",
            ],
            signals={"recommendation": "prolific_tester_excluded"},
            example_creative=example_creative_blob(
                adv_key=a5_key, n=1, media="video", running_days=120,
                link_caption="viralugclabs.com", link_host="viralugclabs.com",
                body="POV: you found the supplement everyone's talking about. New UGC drop daily.",
            ),
            contact_traced=False,
        )
        a5.creatives = [
            make_creative(workspace_id=workspace_id, advertiser_id=a5.id, adv_key=a5_key, n=i,
                          body=f"UGC variation #{i}: POV testimonial hook.",
                          title=f"UGC Hook {i}", link_caption="viralugclabs.com",
                          link_host="viralugclabs.com", media=AdMediaType.VIDEO,
                          running_days=max(3, 120 - i * 3), is_active=i <= 38)
            for i in range(1, 41)
        ]
        advertisers.append(a5)

        db.add_all(advertisers)
        await db.commit()

        print(f"Seeded workspace_id: {workspace_id}")
        print(f"Linked LeadProspect id: {prospect.id} (company=Evergreen Roofing Co)")
        for a in advertisers:
            print(
                f"  {a.advertiser_name:<26} id={a.id} "
                f"score={a.opportunity_score:>3} longest={a.longest_running_active_days:>3}d "
                f"distinct={a.distinct_creative_count:>2} traced={a.contact_traced}"
            )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: seed_ad_library_e2e.py <workspace_id>")
    asyncio.run(seed(uuid.UUID(sys.argv[1])))
