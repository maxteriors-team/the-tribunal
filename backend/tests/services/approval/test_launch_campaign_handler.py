"""Integration tests for the outbound.launch_campaign approval handler."""

from __future__ import annotations

import uuid

import pytest

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.campaign import Campaign, CampaignContact, CampaignStatus, CampaignType
from app.models.contact import Contact
from app.models.pending_action import PendingAction
from app.models.workspace import Workspace
from app.services.approval.approval_gate_service import LaunchCampaignHandler

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared engine pool around each test (loop-affinity safety)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Launch", slug=f"launch-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _draft_campaign(db, workspace_id: uuid.UUID, *, enroll: bool = True) -> Campaign:
    campaign = Campaign(
        workspace_id=workspace_id,
        name="Auto draft",
        campaign_type=CampaignType.SMS,
        status=CampaignStatus.DRAFT,
        from_phone_number="+15125550100",
        initial_message="hi {first_name}",
    )
    db.add(campaign)
    await db.flush()
    if enroll:
        phone = f"+1512555{uuid.uuid4().int % 10000:04d}"
        contact = Contact(
            workspace_id=workspace_id,
            first_name="Lead",
            phone_number=phone,
            phone_hash=hash_phone(phone),
            status="new",
        )
        db.add(contact)
        await db.flush()
        db.add(CampaignContact(campaign_id=campaign.id, contact_id=contact.id))
        await db.flush()
    return campaign


def _action(workspace_id: uuid.UUID, payload: dict) -> PendingAction:
    return PendingAction(
        workspace_id=workspace_id,
        action_type="outbound.launch_campaign",
        action_payload=payload,
        description="Launch the drafted outbound campaign",
        context={"source": "outbound_auto_draft"},
        status="approved",
    )


async def test_approval_starts_draft_campaign() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        campaign = await _draft_campaign(db, ws.id)
        action = _action(ws.id, {"campaign_id": str(campaign.id)})
        db.add(action)
        await db.flush()

        result = await LaunchCampaignHandler().execute(db, action)

        assert result["status"] == "started"
        assert result["campaign_id"] == str(campaign.id)
        assert result["contact_count"] == 1
        assert campaign.status == CampaignStatus.RUNNING
        assert campaign.started_at is not None


async def test_campaign_in_other_workspace_not_found() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        campaign = await _draft_campaign(db, other.id)
        action = _action(ws.id, {"campaign_id": str(campaign.id)})
        db.add(action)
        await db.flush()

        result = await LaunchCampaignHandler().execute(db, action)

        assert result["error"] == "campaign_not_found"
        assert campaign.status == CampaignStatus.DRAFT


async def test_empty_campaign_not_startable() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        campaign = await _draft_campaign(db, ws.id, enroll=False)
        action = _action(ws.id, {"campaign_id": str(campaign.id)})
        db.add(action)
        await db.flush()

        result = await LaunchCampaignHandler().execute(db, action)

        assert result["error"] == "campaign_not_startable"
        assert "no contacts" in result["detail"]
        assert campaign.status == CampaignStatus.DRAFT


async def test_invalid_payload_returns_error() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        action = _action(ws.id, {"campaign_id": "not-a-uuid"})
        db.add(action)
        await db.flush()

        result = await LaunchCampaignHandler().execute(db, action)
        assert result["error"] == "invalid_campaign_id"
