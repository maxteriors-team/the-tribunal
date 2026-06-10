"""Integration tests for ad-library monitor scheduling."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.lead_discovery_job import DiscoveryJobStatus, LeadDiscoveryJob
from app.models.outbound_mission import OutboundMission
from app.models.workspace import Workspace
from app.services.ad_intelligence.monitors import (
    build_monitor_config,
    create_discovery_job_for_monitor,
    due_monitor_missions,
    mark_monitor_scheduled,
    monitor_to_response_dict,
)


def _monitor_mission(workspace_id, *, next_run_at=None, is_active=True) -> OutboundMission:
    config = build_monitor_config(
        name="Roofers running stale ads",
        search={"platform": "meta", "country": "US", "search_terms": "roofing", "max_results": 50},
        icp_thresholds={"min_opportunity_score": 60},
        schedule_interval_hours=24,
        is_active=is_active,
    )
    return OutboundMission(
        workspace_id=workspace_id,
        name="Roofers monitor",
        objective="book_call",
        discovery_config={"ad_monitor": config},
        next_run_at=next_run_at,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_due_monitor_enqueues_job_and_reschedules() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Mon", slug=f"mon-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        # Due now (next_run_at in the past).
        mission = _monitor_mission(ws.id, next_run_at=datetime.now(UTC) - timedelta(hours=1))
        db.add(mission)
        await db.flush()

        due = await due_monitor_missions(db, limit=10)
        assert any(m.id == mission.id for m in due)

        job = create_discovery_job_for_monitor(db, mission)
        mark_monitor_scheduled(mission)
        await db.flush()

        assert job.mission_id == mission.id
        assert job.status == DiscoveryJobStatus.PENDING
        assert job.params["search_terms"] == "roofing"
        # Rescheduled into the future.
        assert mission.next_run_at > datetime.now(UTC)
        assert mission.last_run_at is not None

        job_count = (
            await db.execute(
                select(func.count())
                .select_from(LeadDiscoveryJob)
                .where(LeadDiscoveryJob.mission_id == mission.id)
            )
        ).scalar_one()
        assert job_count == 1

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inactive_monitor_is_skipped() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Mon2", slug=f"mon-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        mission = _monitor_mission(
            ws.id, next_run_at=datetime.now(UTC) - timedelta(hours=1), is_active=False
        )
        db.add(mission)
        await db.flush()

        due = await due_monitor_missions(db, limit=10)
        assert all(m.id != mission.id for m in due)

        # Response shaping carries the saved config.
        shaped = monitor_to_response_dict(mission)
        assert shaped["name"] == "Roofers running stale ads"
        assert shaped["is_active"] is False

        await db.rollback()
