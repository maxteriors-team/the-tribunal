"""Seed a clean workspace for manual advertiser -> CRM promotion verification.

Creates (idempotently):
  * a login user (promote-e2e@example.com / Passw0rd!2026)
  * a dedicated workspace "Promote E2E QA" with the user as owner
  * a default pipeline (so opportunities can be created)
  * four ad-library advertisers, each ICP-qualified and tag-triggering
    (long-runner / stale-creative / no-testing), with a linked prospect:
      - "Promote QA WithPhone Co"  -> prospect WITH phone   (drawer single test)
      - "Promote QA NoPhone Co"    -> prospect WITHOUT phone (no_phone skip test)
      - "Promote QA Bulk One Co"   -> prospect WITH phone   (bulk test)
      - "Promote QA Bulk Two Co"   -> prospect WITH phone   (bulk test)

Re-running wipes and reseeds only the four advertisers + their prospects/contacts
so the run starts from "not yet promoted".

Run: cd backend && uv run python -m scripts.dev.seed_promote_e2e
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.encryption import hash_phone, hash_value
from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal
from app.models.ad_advertiser import AdAdvertiser, AdPlatform
from app.models.ad_creative import AdCreative
from app.models.contact import Contact
from app.models.lead_prospect import (
    LeadProspect,
    ProspectIdentityKind,
    ProspectStatus,
)
from app.models.opportunity import Opportunity
from app.models.pipeline import Pipeline, PipelineStage
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

USER_EMAIL = "promote-e2e@example.com"
USER_PASSWORD = "Passw0rd!2026"
WS_NAME = "Promote E2E QA"
WS_SLUG = "promote-e2e-qa"

NOW = datetime.now(UTC)

_DEFAULT_STAGES = [
    {"name": "New", "order": 0, "probability": 0, "stage_type": "active"},
    {"name": "Qualified", "order": 1, "probability": 25, "stage_type": "active"},
    {"name": "Proposal", "order": 2, "probability": 50, "stage_type": "active"},
    {"name": "Won", "order": 3, "probability": 100, "stage_type": "won"},
    {"name": "Lost", "order": 4, "probability": 0, "stage_type": "lost"},
]


def _example_creative(snippet: str, running_days: int) -> dict:
    return {
        "ad_external_id": f"ad_{uuid.uuid4().hex[:8]}",
        "body_snippet": snippet,
        "link_caption": "Get a free quote",
        "link_url": "https://example.com/quote",
        "snapshot_url": "https://www.facebook.com/ads/library/?id=123",
        "media_type": "video",
        "running_days": running_days,
        "delivery_start_time": (NOW - timedelta(days=running_days)).isoformat(),
    }


def _ad_signal_evidence(adv: AdAdvertiser) -> list[dict]:
    return [
        {
            "type": "ad_signal",
            "source": "ad_library",
            "platform": adv.platform.value,
            "opportunity_score": adv.opportunity_score,
            "longest_running_active_days": adv.longest_running_active_days,
            "distinct_creative_count": adv.distinct_creative_count,
            "active_creative_count": adv.active_creative_count,
            "creative_refresh_rate": adv.creative_refresh_rate,
            "continuity_score": adv.continuity_score,
            "media_mix": adv.media_mix,
            "reasons": adv.reasons,
            "example_creative": adv.example_creative,
            "page_url": adv.page_url,
        }
    ]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # --- user ---
        email_hash = hash_value(USER_EMAIL)
        user = (
            await db.execute(select(User).where(User.email_hash == email_hash))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email=USER_EMAIL,
                email_hash=email_hash,
                hashed_password=get_password_hash(USER_PASSWORD),
                full_name="Promote E2E QA",
                is_active=True,
            )
            db.add(user)
            await db.flush()
        else:
            user.hashed_password = get_password_hash(USER_PASSWORD)
            user.is_active = True

        # --- workspace ---
        ws = (
            await db.execute(select(Workspace).where(Workspace.slug == WS_SLUG))
        ).scalar_one_or_none()
        if ws is None:
            ws = Workspace(name=WS_NAME, slug=WS_SLUG, is_active=True)
            db.add(ws)
            await db.flush()

        # --- membership ---
        member = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.user_id == user.id,
                    WorkspaceMembership.workspace_id == ws.id,
                )
            )
        ).scalar_one_or_none()
        if member is None:
            db.add(
                WorkspaceMembership(
                    user_id=user.id,
                    workspace_id=ws.id,
                    role="owner",
                    is_default=True,
                )
            )

        # --- default pipeline ---
        pipeline = (
            await db.execute(
                select(Pipeline).where(
                    Pipeline.workspace_id == ws.id, Pipeline.is_active.is_(True)
                )
            )
        ).scalars().first()
        if pipeline is None:
            pipeline = Pipeline(
                workspace_id=ws.id,
                name="Sales Pipeline",
                description="Default pipeline",
                is_active=True,
            )
            db.add(pipeline)
            await db.flush()
            for s in _DEFAULT_STAGES:
                db.add(PipelineStage(pipeline_id=pipeline.id, **s))

        await db.flush()

        # --- wipe prior seeded advertisers/prospects/contacts/opps ---
        advs = (
            await db.execute(
                select(AdAdvertiser).where(
                    AdAdvertiser.workspace_id == ws.id,
                    AdAdvertiser.advertiser_key.like("promote-e2e-%"),
                )
            )
        ).scalars().all()
        prospect_ids = [a.prospect_id for a in advs if a.prospect_id]
        for a in advs:
            await db.delete(a)
        await db.flush()
        if prospect_ids:
            contact_ids = (
                await db.execute(
                    select(LeadProspect.contact_id).where(
                        LeadProspect.id.in_(prospect_ids),
                        LeadProspect.contact_id.isnot(None),
                    )
                )
            ).scalars().all()
            await db.execute(
                delete(LeadProspect).where(LeadProspect.id.in_(prospect_ids))
            )
            if contact_ids:
                await db.execute(
                    delete(Opportunity).where(
                        Opportunity.primary_contact_id.in_(contact_ids)
                    )
                )
                await db.execute(delete(Contact).where(Contact.id.in_(contact_ids)))
        await db.flush()

        # --- advertiser specs ---
        specs = [
            ("WithPhone Co", "promot-qa-withphone.example", "+14155550101",
             "Same roofing promo running since spring — book a free inspection."),
            ("NoPhone Co", "promotqa-nophone.example", None,
             "Window replacement special — limited slots this month."),
            ("Bulk One Co", "promotqa-bulk1.example", "+14155550111",
             "Solar install financing — 0% APR for 18 months."),
            ("Bulk Two Co", "promotqa-bulk2.example", "+14155550112",
             "Gutter cleaning bundle — same offer all year."),
        ]

        created = []
        for idx, (label, host, phone, snippet) in enumerate(specs):
            key = f"promote-e2e-{idx}"
            example = _example_creative(snippet, running_days=180)
            adv = AdAdvertiser(
                workspace_id=ws.id,
                platform=AdPlatform.META,
                advertiser_key=key,
                page_id=key,
                advertiser_name=f"Promote QA {label}",
                page_url=f"https://www.facebook.com/{key}",
                website_url=f"https://{host}",
                website_host=host,
                country_code="US",
                first_seen_at=NOW - timedelta(days=200),
                last_seen_at=NOW,
                last_scanned_at=NOW,
                is_active=True,
                signal_window_days=365,
                total_ad_count=3,
                active_ad_count=2,
                distinct_creative_count=2,
                active_creative_count=2,
                longest_running_active_days=180,
                creative_refresh_rate=0.2,
                continuity_score=0.85,
                opportunity_score=90 - idx,
                platform_spread=["facebook", "instagram"],
                media_mix={"video": 2, "image": 1},
                reasons=[
                    "Running the same creative for 180 days.",
                    "Only 2 distinct creatives — not testing.",
                ],
                example_creative=example,
                contact_traced=True,
            )
            db.add(adv)
            await db.flush()

            db.add(
                AdCreative(
                    workspace_id=ws.id,
                    advertiser_id=adv.id,
                    ad_external_id=example["ad_external_id"],
                    body=snippet,
                    title="Free quote",
                    link_url="https://example.com/quote",
                    link_host="example.com",
                    snapshot_url=example["snapshot_url"],
                    ad_delivery_start_time=NOW - timedelta(days=180),
                    is_active=True,
                    first_seen_at=NOW - timedelta(days=180),
                    last_seen_at=NOW,
                )
            )

            prospect = LeadProspect(
                workspace_id=ws.id,
                identity_kind=ProspectIdentityKind.WEBSITE,
                company_name=adv.advertiser_name,
                first_name=adv.advertiser_name,
                website_url=adv.website_url,
                website_host=host,
                website_host_hash=hash_value(host),
                country_code="US",
                source_type="meta_ad_library",
                source_external_id=key,
                dedupe_key=hash_value(f"web:{host}"),
                provenance={"source": "ad_library", "advertiser_key": key},
                evidence=_ad_signal_evidence(adv),
                lead_score=adv.opportunity_score,
                # QUALIFIED so neither the enrichment worker (claims NEW) nor the
                # auto-promotion worker (claims ENRICHED) touches it — the manual
                # UI button must be the first thing to promote it.
                status=ProspectStatus.QUALIFIED,
                last_enriched_at=NOW,
            )
            if phone:
                prospect.phone_number = phone
                prospect.phone_hash = hash_phone(phone)
            db.add(prospect)
            await db.flush()
            adv.prospect_id = prospect.id
            created.append((adv.advertiser_name, str(adv.id), bool(phone)))

        await db.commit()

        print("=== Seed complete ===")
        print(f"login_email   : {USER_EMAIL}")
        print(f"login_password: {USER_PASSWORD}")
        print(f"workspace_id  : {ws.id}")
        print(f"workspace_slug: {ws.slug}")
        print(f"pipeline_id   : {pipeline.id}")
        print("advertisers:")
        for name, aid, has_phone in created:
            print(f"  - {name:28s} id={aid} has_phone={has_phone}")


if __name__ == "__main__":
    asyncio.run(main())
