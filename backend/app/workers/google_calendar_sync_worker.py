"""Google Calendar status-sync worker (polling fallback).

Pulls incremental changes from every active Google connection on a cadence and
maps cancellations/reschedules back onto appointments. This is the dev-friendly
path — it needs no public webhook. In production the push webhook triggers the
same sync immediately; this loop is the safety net that also recovers missed or
expired watch channels.
"""

from __future__ import annotations

from app.core.config import settings
from app.services.calendar.google.oauth import google_oauth_configured
from app.services.calendar.google.sync import sync_all_connections
from app.workers.base import BaseWorker, WorkerRegistry


class GoogleCalendarSyncWorker(BaseWorker):
    """Periodically pull Google Calendar changes into appointment status."""

    POLL_INTERVAL_SECONDS = settings.google_calendar_sync_poll_interval
    COMPONENT_NAME = "google_calendar_sync"
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        if not google_oauth_configured():
            return
        totals = await sync_all_connections()
        if totals.get("changed"):
            self.record_items_processed(totals["changed"])
            self.logger.info("google_calendar_sync_cycle", **totals)


_registry = WorkerRegistry(GoogleCalendarSyncWorker)
start_google_calendar_sync_worker = _registry.start
stop_google_calendar_sync_worker = _registry.stop
get_google_calendar_sync_worker = _registry.get
