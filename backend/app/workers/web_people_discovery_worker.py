"""Web people-discovery worker.

Polls pending ``web_people`` :class:`LeadDiscoveryJob` rows, crawls the target
company domains for named individuals, and upserts one :class:`LeadProspect`
per person through the shared person-dedupe flow. Mirrors the ad-library
discovery worker's claim/lock/commit shape so multiple replicas never
double-run a job.

All heavy crawl I/O stays inside this worker (the single-process worker model);
the search/reveal API never blocks on crawling.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import system_session
from app.models.lead_discovery_job import (
    DiscoveryJobStatus,
    DiscoverySourceType,
    LeadDiscoveryJob,
)
from app.services.lead_discovery.people_discovery import run_people_discovery_job
from app.workers.base import BaseWorker, WorkerRegistry

# Crawls are bounded per-domain; keep the per-tick batch small.
MAX_JOBS_PER_TICK = 2


class WebPeopleDiscoveryWorker(BaseWorker):
    """Execute pending ``web_people`` discovery jobs."""

    POLL_INTERVAL_SECONDS = getattr(settings, "web_people_discovery_poll_interval", 20)
    COMPONENT_NAME = "web_people_discovery_worker"
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        async with system_session("web_people_discovery_worker sweeps every workspace") as db:
            jobs = await self._claim_jobs(db)
            if not jobs:
                return
            self.logger.debug("processing_web_people_jobs", count=len(jobs))
            for job in jobs:
                await self._run_job(db, job)
            await db.commit()

    async def _claim_jobs(self, db: AsyncSession) -> list[LeadDiscoveryJob]:
        result = await db.execute(
            select(LeadDiscoveryJob)
            .where(
                LeadDiscoveryJob.status == DiscoveryJobStatus.PENDING,
                LeadDiscoveryJob.source_type == DiscoverySourceType.WEB_PEOPLE,
            )
            .order_by(LeadDiscoveryJob.created_at)
            .limit(MAX_JOBS_PER_TICK)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def _run_job(self, db: AsyncSession, job: LeadDiscoveryJob) -> None:
        log = self.logger.bind(job_id=str(job.id), workspace_id=str(job.workspace_id))
        try:
            await run_people_discovery_job(db, job)
            self.record_items_processed(1)
        except Exception as exc:  # noqa: BLE001 - record failure, continue batch
            job.status = DiscoveryJobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.error_count = (job.error_count or 0) + 1
            job.last_error = str(exc)[:2000]
            log.exception("web_people_job_failed", error=str(exc))


_registry = WorkerRegistry(WebPeopleDiscoveryWorker)
start_web_people_discovery_worker = _registry.start
stop_web_people_discovery_worker = _registry.stop
get_web_people_discovery_worker = _registry.get
