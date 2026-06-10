"""Integration tests for workspace-level operator nudge strategies.

Covers null-contact creation, per-workspace-per-day dedup, and the
threshold/no-op paths for ``outbound_batch_ready``, ``approvals_waiting``,
and ``monitor_idle``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.campaign import Campaign, CampaignContact, CampaignStatus, CampaignType
from app.models.contact import Contact
from app.models.human_nudge import HumanNudge
from app.models.outbound_mission import OutboundMission
from app.models.pending_action import PendingAction
from app.models.workspace import Workspace
from app.services.ad_intelligence.monitors import build_monitor_config
from app.services.nudges.strategies import (
    ApprovalsWaitingNudgeStrategy,
    MonitorIdleNudgeStrategy,
    NudgeContext,
    OutboundBatchReadyNudgeStrategy,
)
from app.services.nudges.strategies.outbound_batch_ready import MIN_BATCH_SIZE

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared engine pool around each test (loop-affinity safety)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Ops", slug=f"ops-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


def _context(workspace_id: uuid.UUID) -> NudgeContext:
    return NudgeContext(
        workspace_id=workspace_id,
        lead_days=3,
        cooling_days=30,
        enabled_types=["outbound_batch_ready", "approvals_waiting", "monitor_idle"],
    )


def _ad_contact(workspace_id: uuid.UUID, n: int) -> Contact:
    phone = f"+1512555{2000 + n:04d}"
    return Contact(
        workspace_id=workspace_id,
        first_name=f"Lead{n}",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        status="new",
        source="ad_library",
    )


async def _workspace_nudges(db, workspace_id: uuid.UUID) -> list[HumanNudge]:
    result = await db.execute(
        select(HumanNudge).where(HumanNudge.workspace_id == workspace_id)
    )
    return list(result.scalars().all())


class TestOutboundBatchReady:
    async def test_creates_null_contact_nudge_and_dedups(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            for n in range(MIN_BATCH_SIZE):
                db.add(_ad_contact(ws.id, n))
            await db.flush()

            strategy = OutboundBatchReadyNudgeStrategy()
            context = _context(ws.id)
            assert await strategy.generate(db, context) == 1
            await db.flush()

            nudges = await _workspace_nudges(db, ws.id)
            assert len(nudges) == 1
            nudge = nudges[0]
            assert nudge.contact_id is None
            assert nudge.nudge_type == "outbound_batch_ready"
            assert str(MIN_BATCH_SIZE) in nudge.title
            assert nudge.dedup_key == (
                f"{ws.id}:outbound_batch_ready:{context.today.isoformat()}"
            )

            # Same day → deduped.
            assert await strategy.generate(db, context) == 0

    async def test_below_threshold_or_already_enrolled_is_noop(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            # MIN_BATCH_SIZE contacts but one is enrolled in a campaign →
            # below threshold.
            contacts = [_ad_contact(ws.id, 100 + n) for n in range(MIN_BATCH_SIZE)]
            db.add_all(contacts)
            campaign = Campaign(
                workspace_id=ws.id,
                name="Existing",
                campaign_type=CampaignType.SMS,
                status=CampaignStatus.RUNNING,
                from_phone_number="+15125550100",
                initial_message="hi",
            )
            db.add(campaign)
            await db.flush()
            db.add(CampaignContact(campaign_id=campaign.id, contact_id=contacts[0].id))
            await db.flush()

            assert await OutboundBatchReadyNudgeStrategy().generate(db, _context(ws.id)) == 0


class TestApprovalsWaiting:
    async def test_stale_approvals_create_nudge_once(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            db.add(
                PendingAction(
                    workspace_id=ws.id,
                    action_type="send_sms",
                    action_payload={},
                    description="stale",
                    context={},
                    status="pending",
                    created_at=datetime.now(UTC) - timedelta(hours=3),
                )
            )
            await db.flush()

            strategy = ApprovalsWaitingNudgeStrategy()
            context = _context(ws.id)
            assert await strategy.generate(db, context) == 1
            await db.flush()

            nudges = await _workspace_nudges(db, ws.id)
            assert len(nudges) == 1
            assert nudges[0].contact_id is None
            assert nudges[0].nudge_type == "approvals_waiting"

            assert await strategy.generate(db, context) == 0

    async def test_fresh_approvals_do_not_nudge(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            db.add(
                PendingAction(
                    workspace_id=ws.id,
                    action_type="send_sms",
                    action_payload={},
                    description="fresh",
                    context={},
                    status="pending",
                )
            )
            await db.flush()

            assert await ApprovalsWaitingNudgeStrategy().generate(db, _context(ws.id)) == 0


class TestMonitorIdle:
    async def test_no_monitor_creates_nudge_once(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            strategy = MonitorIdleNudgeStrategy()
            context = _context(ws.id)

            assert await strategy.generate(db, context) == 1
            await db.flush()

            nudges = await _workspace_nudges(db, ws.id)
            assert len(nudges) == 1
            assert nudges[0].contact_id is None
            assert nudges[0].nudge_type == "monitor_idle"

            assert await strategy.generate(db, context) == 0

    async def test_active_monitor_suppresses_nudge(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
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
            await db.flush()

            assert await MonitorIdleNudgeStrategy().generate(db, _context(ws.id)) == 0

    async def test_inactive_monitor_still_nudges(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            db.add(
                OutboundMission(
                    workspace_id=ws.id,
                    name="Paused monitor",
                    discovery_config={
                        "ad_monitor": build_monitor_config(
                            name="Paused monitor",
                            search={"search_terms": "roofing"},
                            icp_thresholds={},
                            schedule_interval_hours=24,
                            is_active=False,
                        )
                    },
                )
            )
            await db.flush()

            assert await MonitorIdleNudgeStrategy().generate(db, _context(ws.id)) == 1
