"""Integration tests for the Today Queue mission-list service.

These hit the real database (run with ``-m integration``) because the service
is almost entirely composed of cross-table queries; mocking each execute call
would pin implementation details rather than behaviour.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.campaign import Campaign, CampaignContact, CampaignStatus, CampaignType
from app.models.contact import Contact
from app.models.human_nudge import HumanNudge
from app.models.offer import Offer
from app.models.outbound_mission import OutboundMission
from app.models.pending_action import PendingAction
from app.models.phone_number import PhoneNumber
from app.models.tag import ContactTag, Tag
from app.models.workspace import Workspace
from app.services.ad_intelligence.monitors import build_monitor_config
from app.services.dashboard.today_queue_service import TodayQueueService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared engine pool around each test (loop-affinity safety)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Today", slug=f"today-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


def _contact(workspace_id: uuid.UUID, *, phone: str, **kw) -> Contact:
    base = {
        "workspace_id": workspace_id,
        "first_name": "Lead",
        "phone_number": phone,
        "phone_hash": hash_phone(phone),
        "status": "new",
    }
    base.update(kw)
    return Contact(**base)


async def test_empty_workspace_surfaces_only_setup_gaps() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        queue = await TodayQueueService(db).get_today_queue(ws.id)

        kinds = [item.kind for item in queue.items]
        assert kinds == ["setup_gap", "setup_gap", "setup_gap"]
        gaps = {item.payload["gap"] for item in queue.items}
        assert gaps == {"monitor", "offer", "phone"}


async def test_queue_is_ordered_and_complete() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        now = datetime.now(UTC)

        # Approvals (top priority).
        db.add(
            PendingAction(
                workspace_id=ws.id,
                action_type="send_sms",
                action_payload={},
                description="Send intro SMS to Acme Co",
                context={},
                status="pending",
            )
        )

        # Hot nudge due today.
        db.add(
            HumanNudge(
                workspace_id=ws.id,
                contact_id=None,
                nudge_type="outbound_batch_ready",
                title="Fresh advertisers ready",
                message="Review the batch",
                priority="high",
                due_date=now,
                status="pending",
                dedup_key=f"test:{uuid.uuid4().hex}",
            )
        )

        # Fresh ad-library batch with a signal tag.
        contact = _contact(
            ws.id, phone="+15125550199", source="ad_library", company_name="Acme Co"
        )
        db.add(contact)
        await db.flush()
        tag = Tag(workspace_id=ws.id, name="stale-creative")
        db.add(tag)
        await db.flush()
        db.add(ContactTag(contact_id=contact.id, tag_id=tag.id))

        # Draft campaign with one enrolled contact.
        campaign = Campaign(
            workspace_id=ws.id,
            name="Ad library blast",
            campaign_type=CampaignType.SMS,
            status=CampaignStatus.DRAFT,
            from_phone_number="+15125550100",
            initial_message="hi {first_name}",
        )
        db.add(campaign)
        await db.flush()
        db.add(CampaignContact(campaign_id=campaign.id, contact_id=contact.id))

        # Setup state: active monitor + active offer + sms number → no gaps.
        db.add(
            OutboundMission(
                workspace_id=ws.id,
                name="Monitor",
                discovery_config={
                    "ad_monitor": build_monitor_config(
                        name="Monitor",
                        search={"search_terms": "roofing"},
                        icp_thresholds={},
                        schedule_interval_hours=24,
                    )
                },
            )
        )
        db.add(Offer(workspace_id=ws.id, name="Free audit", is_active=True))
        db.add(
            PhoneNumber(
                workspace_id=ws.id,
                phone_number=f"+1512555{uuid.uuid4().int % 10000:04d}",
                is_active=True,
                sms_enabled=True,
            )
        )
        await db.flush()

        queue = await TodayQueueService(db).get_today_queue(ws.id)
        kinds = [item.kind for item in queue.items]
        assert kinds == ["approvals", "hot_nudges", "prospect_batch", "draft_campaign"]

        approvals, nudges, batch, draft = queue.items
        assert approvals.count == 1
        assert "Send intro SMS to Acme Co" in approvals.body
        assert approvals.href == "/pending-actions"

        assert nudges.count == 1
        assert "Fresh advertisers ready" in nudges.body
        assert nudges.href == "/nudges"

        assert batch.count == 1
        assert "Acme Co" in batch.body
        assert batch.payload["signal_tags"] == ["stale-creative"]
        assert batch.href == "/find-leads/ad-library"

        assert draft.count == 1
        assert draft.payload["campaign_id"] == str(campaign.id)
        assert draft.href == f"/campaigns/{campaign.id}"


async def test_stale_contacts_and_foreign_workspace_excluded() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        old = datetime.now(UTC) - timedelta(days=3)

        # Old ad-library contact: outside the 24h batch window.
        db.add(
            _contact(ws.id, phone="+15125550111", source="ad_library", created_at=old)
        )
        # Fresh contact, but in another workspace.
        db.add(_contact(other.id, phone="+15125550112", source="ad_library"))
        # Fresh contact in this workspace, but not from the ad library.
        db.add(_contact(ws.id, phone="+15125550113", source="manual"))
        # Pending approval in the other workspace only.
        db.add(
            PendingAction(
                workspace_id=other.id,
                action_type="send_sms",
                action_payload={},
                description="other ws",
                context={},
                status="pending",
            )
        )
        await db.flush()

        queue = await TodayQueueService(db).get_today_queue(ws.id)
        kinds = {item.kind for item in queue.items}
        assert "prospect_batch" not in kinds
        assert "approvals" not in kinds


async def test_snoozed_and_future_nudges_not_counted() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        now = datetime.now(UTC)
        tomorrow = now + timedelta(days=2)

        db.add(
            HumanNudge(
                workspace_id=ws.id,
                contact_id=None,
                nudge_type="monitor_idle",
                title="Snoozed",
                message="m",
                due_date=now,
                status="snoozed",
                dedup_key=f"test:{uuid.uuid4().hex}",
            )
        )
        db.add(
            HumanNudge(
                workspace_id=ws.id,
                contact_id=None,
                nudge_type="monitor_idle",
                title="Future",
                message="m",
                due_date=tomorrow,
                status="pending",
                dedup_key=f"test:{uuid.uuid4().hex}",
            )
        )
        await db.flush()

        queue = await TodayQueueService(db).get_today_queue(ws.id)
        assert all(item.kind != "hot_nudges" for item in queue.items)
