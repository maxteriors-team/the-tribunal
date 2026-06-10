"""Ad-library monitor worker.

Periodically re-runs saved ad-library monitors (saved searches stored on
:class:`~app.models.outbound_mission.OutboundMission` discovery_config). For
each due monitor it enqueues a fresh ad-library :class:`LeadDiscoveryJob`; the
discovery worker then re-queries the advertisers, and because the upsert is
idempotent + signals recompute, active/stop times refresh over time — proving
"still running the same ad".

Lightweight by design: this worker only *schedules* re-scans (cheap DB writes),
so it never makes provider API calls itself and can poll frequently without
touching the Meta hourly budget.
"""

from __future__ import annotations

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.ad_intelligence.monitors import (
    create_discovery_job_for_monitor,
    due_monitor_missions,
    mark_monitor_scheduled,
)
from app.workers.base import BaseWorker, WorkerRegistry

MAX_MONITORS_PER_TICK = 10


class AdMonitorWorker(BaseWorker):
    """Enqueue re-scan jobs for due ad-library monitors."""

    POLL_INTERVAL_SECONDS = getattr(settings, "ad_monitor_poll_interval", 300)
    COMPONENT_NAME = "ad_monitor_worker"
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        async with AsyncSessionLocal() as db:
            missions = await due_monitor_missions(db, limit=MAX_MONITORS_PER_TICK)
            if not missions:
                return
            self.logger.debug("scheduling_ad_monitors", count=len(missions))
            for mission in missions:
                job = create_discovery_job_for_monitor(db, mission)
                mark_monitor_scheduled(mission)
                self.logger.info(
                    "ad_monitor_rescan_scheduled",
                    mission_id=str(mission.id),
                    job_id=str(job.id),
                    next_run_at=mission.next_run_at.isoformat() if mission.next_run_at else None,
                )
                self.record_items_processed(1)
            await db.commit()


_registry = WorkerRegistry(AdMonitorWorker)
start_ad_monitor_worker = _registry.start
stop_ad_monitor_worker = _registry.stop
get_ad_monitor_worker = _registry.get
