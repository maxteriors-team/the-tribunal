"""Auth rate-limit cleanup worker.

The ``auth_rate_limits`` table is append-only: every authentication attempt
(login, register, refresh, plus per-failure rows for username lockout) writes
a new row. Without periodic pruning the table grows unbounded — degrading
the hot windowed-count queries that gate every auth request.

This worker deletes rows older than ``RETENTION_HOURS`` (24h, far longer
than the 15-minute IP rate-limit and username-lockout windows in
``app/api/v1/auth.py``) on an hourly cadence. The retention buffer is
deliberately generous so an in-flight check can never race a deletion of
a row that still falls inside its evaluation window.

See ``docs/decisions/auth-rate-limit-cleanup.md`` for the decision record
on why we kept the DB-backed limiter and added cleanup rather than moving
to Redis.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.db.session import system_session
from app.models.auth_rate_limit import AuthRateLimit
from app.workers.base import BaseWorker, WorkerRegistry

# Retention window — rows older than this are deleted each cycle.
# Must comfortably exceed the longest rate-limit window evaluated in
# ``app/api/v1/auth.py`` (currently 15 minutes for both IP rate-limit and
# username lockout). 24h gives a wide safety margin and keeps the table
# small enough that the windowed-count queries stay on the composite index.
RETENTION_HOURS = 24

# Run hourly. Deletion is cheap (indexed range delete), so a tighter cadence
# would just add log noise without changing the steady-state row count.
POLL_INTERVAL_SECONDS = 3600


class AuthRateLimitCleanupWorker(BaseWorker):
    """Delete ``auth_rate_limits`` rows older than the retention window."""

    POLL_INTERVAL_SECONDS = POLL_INTERVAL_SECONDS
    COMPONENT_NAME = "auth_rate_limit_cleanup"
    # One bulk DELETE per cycle — no fan-out, no concurrency needed.
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(hours=RETENTION_HOURS)
        async with system_session("auth_rate_limit_cleanup_worker sweeps every workspace") as db:
            result = await db.execute(
                delete(AuthRateLimit).where(AuthRateLimit.created_at < cutoff)
            )
            await db.commit()

        deleted = int(result.rowcount or 0)  # type: ignore[attr-defined]
        if deleted:
            self.record_items_processed(deleted)
            self.logger.info(
                "auth_rate_limit_rows_deleted",
                deleted=deleted,
                cutoff=cutoff.isoformat(),
                retention_hours=RETENTION_HOURS,
            )


# Singleton registry
_registry = WorkerRegistry(AuthRateLimitCleanupWorker)
start_auth_rate_limit_cleanup_worker = _registry.start
stop_auth_rate_limit_cleanup_worker = _registry.stop
get_auth_rate_limit_cleanup_worker = _registry.get
