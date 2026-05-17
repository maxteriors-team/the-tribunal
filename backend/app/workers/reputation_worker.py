"""Background worker for phone number reputation updates."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.phone_number import PhoneNumber
from app.services.rate_limiting.reputation_tracker import ReputationTracker
from app.services.rate_limiting.warming_scheduler import WarmingScheduler
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker


class ReputationWorker(RetryableWorker, BaseWorker):
    """Background worker for phone number reputation management.

    Periodically:
    - Updates reputation metrics for all active phone numbers
    - Advances warming stages for numbers in warming
    - Logs quarantine events for alerting
    """

    POLL_INTERVAL_SECONDS = getattr(settings, "reputation_poll_interval", 300)
    COMPONENT_NAME = "reputation_worker"
    # Per-phone updates are small DB writes — modest concurrency is fine.
    MAX_CONCURRENCY = 5
    max_retries = 3
    backoff_base_seconds = 2.0

    def __init__(self) -> None:
        super().__init__()
        self.tracker = ReputationTracker()
        self.warming = WarmingScheduler()

    async def _process_items(self) -> None:
        """Update reputation for all active phone numbers."""
        async with AsyncSessionLocal() as db:
            # Get all active phone numbers
            result = await db.execute(select(PhoneNumber).where(PhoneNumber.is_active.is_(True)))
            phones = result.scalars().all()

            updated_count = 0
            warming_advanced = 0
            quarantined_count = 0

            for phone in phones:
                outcome = await self.execute_with_retry(
                    self._update_one_phone,
                    phone,
                    db,
                    item_key=f"phone:{phone.id}",
                )
                if outcome is None:
                    continue
                was_advanced, was_quarantined = outcome
                if was_quarantined:
                    quarantined_count += 1
                if was_advanced:
                    warming_advanced += 1
                updated_count += 1

            self.logger.info(
                "reputation_update_cycle_completed",
                phones_updated=updated_count,
                warming_advanced=warming_advanced,
                newly_quarantined=quarantined_count,
            )

    async def _update_one_phone(self, phone: PhoneNumber, db: AsyncSession) -> tuple[bool, bool]:
        """Update reputation for a single phone. Returns (advanced, quarantined)."""
        old_status = phone.health_status

        await self.tracker.update_phone_reputation(phone.id, db)
        await db.refresh(phone)

        was_quarantined = old_status != "quarantined" and phone.health_status == "quarantined"
        if was_quarantined:
            self.logger.warning(
                "phone_number_quarantined",
                phone_number=phone.phone_number,
                phone_number_id=str(phone.id),
                reason=phone.quarantine_reason,
            )

        was_advanced = False
        if phone.warming_stage > 0:
            was_advanced = bool(await self.warming.advance_warming_stage(phone, db))

        return was_advanced, was_quarantined


# Singleton registry (consistent with all other workers)
_registry = WorkerRegistry(ReputationWorker)
start_reputation_worker = _registry.start
stop_reputation_worker = _registry.stop
get_reputation_worker = _registry.get
