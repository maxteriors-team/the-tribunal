"""Integration tests for the outbound autopilot draft worker."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.campaign import Campaign, CampaignContact, CampaignStatus
from app.models.contact import Contact
from app.models.human_nudge import HumanNudge
from app.models.offer import Offer
from app.models.pending_action import PendingAction
from app.models.phone_number import PhoneNumber
from app.models.segment import Segment
from app.models.workspace import Workspace
from app.workers.outbound_auto_draft_worker import (
    LAUNCH_ACTION_TYPE,
    MANAGED_SEGMENT_NAME,
    MIN_BATCH_SIZE,
    OutboundAutoDraftWorker,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared engine pool around each test (loop-affinity safety)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _setup_workspace(db, *, with_offer: bool = True, contacts: int = MIN_BATCH_SIZE):
    """Workspace with autopilot on, fresh ad-library contacts, and SMS number."""
    ws = Workspace(id=uuid.uuid4(), name="Auto", slug=f"auto-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()

    offer = None
    if with_offer:
        offer = Offer(workspace_id=ws.id, name="Creative audit", is_active=True)
        db.add(offer)
        await db.flush()

    settings = {"outbound_autopilot": {"enabled": True}}
    if offer is not None:
        settings["outbound_autopilot"]["offer_id"] = str(offer.id)
    ws.settings = settings

    for n in range(contacts):
        phone = f"+1512555{4000 + n:04d}"
        db.add(
            Contact(
                workspace_id=ws.id,
                first_name=f"Lead{n}",
                phone_number=phone,
                phone_hash=hash_phone(phone),
                status="new",
                source="ad_library",
            )
        )
    db.add(
        PhoneNumber(
            workspace_id=ws.id,
            phone_number=f"+1512666{uuid.uuid4().int % 10000:04d}",
            is_active=True,
            sms_enabled=True,
        )
    )
    await db.flush()
    await db.commit()
    return ws


async def _launch_actions(db, workspace_id: uuid.UUID) -> list[PendingAction]:
    result = await db.execute(
        select(PendingAction).where(
            PendingAction.workspace_id == workspace_id,
            PendingAction.action_type == LAUNCH_ACTION_TYPE,
        )
    )
    return list(result.scalars().all())


async def test_draft_created_and_parked_behind_approval() -> None:
    worker = OutboundAutoDraftWorker()
    async with AsyncSessionLocal() as db:
        ws = await _setup_workspace(db)

        await worker._process_items()

        actions = await _launch_actions(db, ws.id)
        assert len(actions) == 1
        action = actions[0]
        assert action.status == "pending"
        assert "ad-library contact" in action.description
        assert action.context["source"] == "outbound_auto_draft"

        campaign_id = uuid.UUID(action.action_payload["campaign_id"])
        campaign = await db.get(Campaign, campaign_id)
        assert campaign is not None
        assert campaign.status == CampaignStatus.DRAFT

        # Full batch enrolled, not just the 3 previews.
        enrolled = await db.execute(
            select(func.count())
            .select_from(CampaignContact)
            .where(CampaignContact.campaign_id == campaign_id)
        )
        assert (enrolled.scalar() or 0) == MIN_BATCH_SIZE

        # Managed segment provisioned.
        segment = await db.execute(
            select(Segment).where(
                Segment.workspace_id == ws.id, Segment.name == MANAGED_SEGMENT_NAME
            )
        )
        assert segment.scalar_one_or_none() is not None


async def test_second_tick_same_day_is_idempotent() -> None:
    worker = OutboundAutoDraftWorker()
    async with AsyncSessionLocal() as db:
        ws = await _setup_workspace(db)

        await worker._process_items()
        await worker._process_items()

        actions = await _launch_actions(db, ws.id)
        assert len(actions) == 1


async def test_missing_offer_emits_nudge_instead_of_guessing() -> None:
    worker = OutboundAutoDraftWorker()
    async with AsyncSessionLocal() as db:
        ws = await _setup_workspace(db, with_offer=False)

        await worker._process_items()
        # Second tick must not duplicate the nudge (per-day dedup).
        await worker._process_items()

        assert await _launch_actions(db, ws.id) == []
        nudges = await db.execute(
            select(HumanNudge).where(HumanNudge.workspace_id == ws.id)
        )
        rows = list(nudges.scalars().all())
        assert len(rows) == 1
        assert rows[0].contact_id is None
        assert "offer" in rows[0].message.lower()


async def test_autopilot_off_does_nothing() -> None:
    worker = OutboundAutoDraftWorker()
    async with AsyncSessionLocal() as db:
        ws = await _setup_workspace(db)
        ws.settings = {"outbound_autopilot": {"enabled": False}}
        await db.commit()

        await worker._process_items()

        assert await _launch_actions(db, ws.id) == []


async def test_small_batch_skipped() -> None:
    worker = OutboundAutoDraftWorker()
    async with AsyncSessionLocal() as db:
        ws = await _setup_workspace(db, contacts=MIN_BATCH_SIZE - 1)

        await worker._process_items()

        assert await _launch_actions(db, ws.id) == []
