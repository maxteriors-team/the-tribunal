"""Seed realistic people + buying signals into a workspace for People Search E2E.

Idempotent: clears prior seed rows (tagged via provenance.seed_tag) and re-inserts.
Prints a fresh access token for the workspace owner so a browser session can be
driven against the live UI.

Run:  uv run python scripts/dev/seed_people_search_e2e.py
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, select

from app.core.encryption import hash_value
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.models.lead_prospect import (
    LeadProspect,
    ProspectIdentityKind,
    ProspectStatus,
)
from app.models.outbound_mission import OutboundMission
from app.models.prospect_signal import (
    ProspectSignal,
    ProspectSignalStatus,
    ProspectSignalType,
)
from app.models.workspace import WorkspaceMembership

WORKSPACE_ID = uuid.UUID("4d0af32a-cafd-4298-a238-93d6f8d8b6a4")  # Promote E2E QA
SEED_TAG = "people_search_e2e"

PEOPLE = [
    # full_name, first, last, title, company, host, city, region, score, has_email, status, signals
    (
        "Dana Whitfield",
        "Dana",
        "Whitfield",
        "Head of Marketing",
        "Acme Roofing",
        "acmeroofing.com",
        "Austin",
        "TX",
        92,
        True,
        ProspectStatus.ENRICHED,
        [(ProspectSignalType.RUNNING_ADS, 90), (ProspectSignalType.AD_TECH, 70)],
    ),
    (
        "Marcus Lee",
        "Marcus",
        "Lee",
        "CEO",
        "Lone Star HVAC",
        "lonestarhvac.com",
        "Austin",
        "TX",
        88,
        False,
        ProspectStatus.NEW,
        [(ProspectSignalType.RUNNING_ADS, 85), (ProspectSignalType.HIRING, 60)],
    ),
    (
        "Priya Nair",
        "Priya",
        "Nair",
        "VP Growth",
        "Hill Country Solar",
        "hillcountrysolar.com",
        "Dallas",
        "TX",
        81,
        True,
        ProspectStatus.ENRICHED,
        [(ProspectSignalType.FUNDING, 95)],
    ),
    (
        "Tom Becker",
        "Tom",
        "Becker",
        "Owner",
        "Becker Landscaping",
        "beckerlandscaping.com",
        "Round Rock",
        "TX",
        74,
        False,
        ProspectStatus.NEW,
        [(ProspectSignalType.AD_TECH, 55)],
    ),
    (
        "Sara Kim",
        "Sara",
        "Kim",
        "Marketing Director",
        "BrightPath Dental",
        "brightpathdental.com",
        "Houston",
        "TX",
        69,
        False,
        ProspectStatus.NEW,
        [],
    ),
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # Owner of the workspace -> token subject.
        owner = (
            (
                await db.execute(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == WORKSPACE_ID
                    )
                )
            )
            .scalars()
            .first()
        )
        if owner is None:
            raise SystemExit(f"No membership found for workspace {WORKSPACE_ID}")

        # Wipe prior seed rows (signals first via cascade-safe explicit delete).
        prior = (
            (
                await db.execute(
                    select(LeadProspect.id).where(
                        LeadProspect.workspace_id == WORKSPACE_ID,
                        LeadProspect.source_query == SEED_TAG,
                    )
                )
            )
            .scalars()
            .all()
        )
        if prior:
            await db.execute(delete(ProspectSignal).where(ProspectSignal.prospect_id.in_(prior)))
            await db.execute(delete(LeadProspect).where(LeadProspect.id.in_(prior)))

        # Ensure a mission exists to test "Add to mission".
        mission = (
            (
                await db.execute(
                    select(OutboundMission).where(
                        OutboundMission.workspace_id == WORKSPACE_ID,
                        OutboundMission.name == "People Search QA Mission",
                    )
                )
            )
            .scalars()
            .first()
        )
        if mission is None:
            mission = OutboundMission(
                workspace_id=WORKSPACE_ID,
                name="People Search QA Mission",
            )
            db.add(mission)

        for (
            full,
            first,
            last,
            title,
            company,
            host,
            city,
            region,
            score,
            has_email,
            status,
            signals,
        ) in PEOPLE:
            prospect = LeadProspect(
                workspace_id=WORKSPACE_ID,
                identity_kind=ProspectIdentityKind.OWNER_NAME,
                first_name=first,
                last_name=last,
                full_name=full,
                title=title,
                company_name=company,
                website_url=f"https://{host}",
                website_host=host,
                website_host_hash=hash_value(host),
                city=city,
                region=region,
                country_code="US",
                location_label=f"{city}, {region}",
                source_type="manual",
                source_query=SEED_TAG,
                lead_score=score,
                status=status,
                provenance={"seed_tag": SEED_TAG},
            )
            if has_email:
                email = f"{first.lower()}.{last.lower()}@{host}"
                prospect.email = email
                prospect.email_hash = hash_value(email)
            db.add(prospect)
            await db.flush()  # get prospect.id

            for sig_type, strength in signals:
                db.add(
                    ProspectSignal(
                        workspace_id=WORKSPACE_ID,
                        prospect_id=prospect.id,
                        signal_type=sig_type,
                        strength=strength,
                        status=ProspectSignalStatus.ACTIVE,
                        source="seed",
                        payload={"seed_tag": SEED_TAG},
                    )
                )

        await db.commit()

        token = create_access_token(data={"sub": str(owner.user_id)})
        print("SEED_OK")
        print(f"WORKSPACE_ID={WORKSPACE_ID}")
        print(f"USER_ID={owner.user_id}")
        print(f"ACCESS_TOKEN={token}")


if __name__ == "__main__":
    asyncio.run(main())
