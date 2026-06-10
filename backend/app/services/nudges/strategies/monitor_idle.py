"""Operator-level nudge: the ad-library scraper has no active monitor."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.human_nudge import HumanNudge
from app.models.outbound_mission import OutboundMission
from app.services.ad_intelligence.monitors import AD_MONITOR_KEY, is_active_monitor
from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    dedup_exists,
)


class MonitorIdleNudgeStrategy(NudgeStrategy):
    """Nudge the operator when no active ad-library monitor exists.

    Without a monitor, the overnight scrape → morning batch loop is off and
    no fresh advertisers land in the queue. Workspace-level
    (``contact_id=None``), deduped per workspace per day.
    """

    nudge_type = "monitor_idle"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        dedup_key = f"{context.workspace_id}:monitor_idle:{context.today.isoformat()}"
        if await dedup_exists(db, dedup_key):
            return 0

        result = await db.execute(
            select(OutboundMission).where(
                OutboundMission.workspace_id == context.workspace_id,
                OutboundMission.discovery_config[AD_MONITOR_KEY].isnot(None),
            )
        )
        if any(is_active_monitor(m) for m in result.scalars().all()):
            return 0

        db.add(
            HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=None,
                nudge_type="monitor_idle",
                title="\U0001f6f0\ufe0f The scraper is off — set a monitor",
                message=(
                    "\U0001f6f0\ufe0f No active ad-library monitor is running, so no fresh "
                    "advertisers will land in your queue. Save a recurring search to turn "
                    "the machine back on."
                ),
                suggested_action=None,
                priority="medium",
                due_date=context.now,
                source_date_field=None,
                status="pending",
                dedup_key=dedup_key,
            )
        )
        return 1
