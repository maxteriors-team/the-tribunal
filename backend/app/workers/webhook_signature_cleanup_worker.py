"""Webhook signature ledger cleanup worker.

The ``seen_webhook_signatures`` table is append-only: every accepted signed
webhook delivery writes one row (see
:mod:`app.services.webhook_replay`). Without pruning it grows forever and the
UNIQUE-constraint probe on the hot webhook path slowly degrades.

This worker deletes rows older than
:data:`~app.services.webhook_replay.SIGNATURE_RETENTION_DAYS` once a day. The
retention window is a security boundary, not a retry window: while a signature
is in the table a captured ``(body, signature)`` pair cannot be replayed. Past
it, a very patient attacker could replay a capture again — which is why the
webhook secret should be rotated if a capture is ever suspected, and why the
window is measured in weeks rather than hours.

Structure deliberately mirrors
:mod:`app.workers.auth_rate_limit_cleanup_worker`: one indexed range delete per
cycle, no fan-out.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.models.webhook_signature import SeenWebhookSignature
from app.services.webhook_replay import SIGNATURE_RETENTION_DAYS
from app.workers.base import BaseWorker, WorkerRegistry

# Retention is owned by the replay service so the security window and the
# pruning window can never drift apart.
RETENTION_DAYS = SIGNATURE_RETENTION_DAYS

# Daily. The retention window is 30 days, so a tighter cadence would delete the
# same (empty) range over and over; one indexed range delete per day keeps the
# table bounded with negligible cost.
POLL_INTERVAL_SECONDS = 86400


class WebhookSignatureCleanupWorker(BaseWorker):
    """Delete ``seen_webhook_signatures`` rows older than the retention window."""

    POLL_INTERVAL_SECONDS = POLL_INTERVAL_SECONDS
    COMPONENT_NAME = "webhook_signature_cleanup"
    # One bulk DELETE per cycle — no fan-out, no concurrency needed.
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                delete(SeenWebhookSignature).where(SeenWebhookSignature.created_at < cutoff)
            )
            await db.commit()

        deleted = int(result.rowcount or 0)  # type: ignore[attr-defined]
        if deleted:
            self.record_items_processed(deleted)
            self.logger.info(
                "seen_webhook_signature_rows_deleted",
                deleted=deleted,
                cutoff=cutoff.isoformat(),
                retention_days=RETENTION_DAYS,
            )


# Singleton registry
_registry = WorkerRegistry(WebhookSignatureCleanupWorker)
start_webhook_signature_cleanup_worker = _registry.start
stop_webhook_signature_cleanup_worker = _registry.stop
get_webhook_signature_cleanup_worker = _registry.get
