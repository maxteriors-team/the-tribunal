"""Track phone number reputation and health metrics."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phone_number import PhoneNumber, PhoneNumberHealthStatus
from app.models.phone_number_stats import PhoneNumberDailyStats

logger = structlog.get_logger()


class ReputationTracker:
    """Monitor and update phone number reputation metrics.

    Tracks 7-day rolling averages for:
    - Delivery rate
    - Bounce rate (hard bounces)
    - Spam complaint rate

    Automatically quarantines numbers that exceed thresholds.
    """

    # Health thresholds - recommended values for 10DLC compliance
    MAX_BOUNCE_RATE = 0.05  # 5% hard bounce rate triggers quarantine
    MAX_COMPLAINT_RATE = 0.001  # 0.1% spam complaint rate triggers quarantine
    MIN_DELIVERY_RATE = 0.90  # Below 90% delivery triggers cooldown
    MIN_MESSAGES_FOR_EVALUATION = 50  # Minimum messages before evaluating rates

    def __init__(self) -> None:
        self.logger = logger.bind(component="reputation_tracker")

    async def update_phone_reputation(
        self,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Recalculate reputation metrics for a phone number.

        Aggregates daily stats from the last 7 days and updates
        the phone number's reputation fields.

        Args:
            phone_number_id: Phone number UUID
            db: Database session
        """
        log = self.logger.bind(phone_number_id=str(phone_number_id))

        # Get phone number
        result = await db.execute(
            select(PhoneNumber).where(PhoneNumber.id == phone_number_id)
        )
        phone = result.scalar_one_or_none()
        if not phone:
            log.warning("phone_number_not_found")
            return

        # Calculate 7-day window stats
        seven_days_ago = datetime.now(UTC) - timedelta(days=7)

        stats_result = await db.execute(
            select(
                func.coalesce(func.sum(PhoneNumberDailyStats.messages_sent), 0).label(
                    "sent"
                ),
                func.coalesce(func.sum(PhoneNumberDailyStats.messages_delivered), 0).label(
                    "delivered"
                ),
                func.coalesce(func.sum(PhoneNumberDailyStats.hard_bounces), 0).label(
                    "hard_bounces"
                ),
                func.coalesce(func.sum(PhoneNumberDailyStats.soft_bounces), 0).label(
                    "soft_bounces"
                ),
                func.coalesce(func.sum(PhoneNumberDailyStats.spam_complaints), 0).label(
                    "complaints"
                ),
                func.coalesce(func.sum(PhoneNumberDailyStats.opt_outs), 0).label(
                    "opt_outs"
                ),
            ).where(
                and_(
                    PhoneNumberDailyStats.phone_number_id == phone_number_id,
                    PhoneNumberDailyStats.date >= seven_days_ago.date(),
                )
            )
        )
        stats = stats_result.one()

        # Update 7-day totals
        phone.messages_sent_7d = int(stats.sent)
        phone.messages_delivered_7d = int(stats.delivered)
        phone.hard_bounces_7d = int(stats.hard_bounces)
        phone.soft_bounces_7d = int(stats.soft_bounces)
        phone.spam_complaints_7d = int(stats.complaints)
        phone.opt_outs_7d = int(stats.opt_outs)

        # Calculate rates
        total_sent = phone.messages_sent_7d
        if total_sent > 0:
            phone.delivery_rate = phone.messages_delivered_7d / total_sent
            phone.bounce_rate = phone.hard_bounces_7d / total_sent
            phone.complaint_rate = phone.spam_complaints_7d / total_sent
        else:
            phone.delivery_rate = 0.0
            phone.bounce_rate = 0.0
            phone.complaint_rate = 0.0

        # Check thresholds and update health status
        await self._check_health_thresholds(phone, log)

        await db.commit()

        log.info(
            "reputation_updated",
            phone_number=phone.phone_number,
            delivery_rate=round(phone.delivery_rate, 4),
            bounce_rate=round(phone.bounce_rate, 4),
            complaint_rate=round(phone.complaint_rate, 6),
            health_status=phone.health_status,
            messages_sent_7d=phone.messages_sent_7d,
        )

    async def _check_health_thresholds(
        self,
        phone: PhoneNumber,
        log: Any,
    ) -> None:
        """Check if phone number should be quarantined or cooled down.

        Args:
            phone: Phone number model
            log: Bound logger
        """
        # Skip if already quarantined and not reviewed
        if (
            phone.health_status == PhoneNumberHealthStatus.QUARANTINED
            and not phone.quarantine_reviewed
        ):
            return

        # Skip evaluation if not enough messages
        if phone.messages_sent_7d < self.MIN_MESSAGES_FOR_EVALUATION:
            return

        # Check for critical violations (quarantine)
        if phone.bounce_rate > self.MAX_BOUNCE_RATE:
            phone.health_status = PhoneNumberHealthStatus.QUARANTINED
            phone.quarantined_at = datetime.now(UTC)
            phone.quarantine_reason = f"High bounce rate: {phone.bounce_rate:.2%}"
            phone.quarantine_reviewed = False
            log.warning(
                "number_quarantined_bounce_rate",
                phone_number=phone.phone_number,
                rate=phone.bounce_rate,
            )

        elif phone.complaint_rate > self.MAX_COMPLAINT_RATE:
            phone.health_status = PhoneNumberHealthStatus.QUARANTINED
            phone.quarantined_at = datetime.now(UTC)
            phone.quarantine_reason = f"High complaint rate: {phone.complaint_rate:.4%}"
            phone.quarantine_reviewed = False
            log.warning(
                "number_quarantined_complaint_rate",
                phone_number=phone.phone_number,
                rate=phone.complaint_rate,
            )

        elif phone.delivery_rate < self.MIN_DELIVERY_RATE:
            # Low delivery rate = cooldown (less severe)
            if phone.health_status not in [
                PhoneNumberHealthStatus.COOLDOWN,
                PhoneNumberHealthStatus.QUARANTINED,
            ]:
                phone.health_status = PhoneNumberHealthStatus.COOLDOWN
                log.warning(
                    "number_cooldown_delivery_rate",
                    phone_number=phone.phone_number,
                    rate=phone.delivery_rate,
                )

        elif phone.health_status == PhoneNumberHealthStatus.COOLDOWN:
            # Number recovered - mark as healthy
            phone.health_status = PhoneNumberHealthStatus.HEALTHY
            log.info(
                "number_recovered_from_cooldown",
                phone_number=phone.phone_number,
            )

    async def record_daily_stats(
        self,
        phone_number_id: uuid.UUID,
        date: datetime,
        db: AsyncSession,
    ) -> PhoneNumberDailyStats:
        """Get or create daily stats record for a phone number.

        Uses ``INSERT ... ON CONFLICT DO NOTHING`` against the
        ``uq_phone_daily_stats`` unique constraint so concurrent callers
        don't both try to insert the same (phone_number_id, date) row.

        Args:
            phone_number_id: Phone number UUID
            date: Date to record stats for
            db: Database session

        Returns:
            Daily stats record
        """
        stats_date = date.date() if isinstance(date, datetime) else date

        await self._ensure_daily_stats_row(phone_number_id, stats_date, db)

        result = await db.execute(
            select(PhoneNumberDailyStats).where(
                and_(
                    PhoneNumberDailyStats.phone_number_id == phone_number_id,
                    PhoneNumberDailyStats.date == stats_date,
                )
            )
        )
        stats = result.scalar_one()
        return stats

    async def _ensure_daily_stats_row(
        self,
        phone_number_id: uuid.UUID,
        stats_date: date,
        db: AsyncSession,
    ) -> None:
        """Ensure a daily stats row exists for (phone_number_id, stats_date).

        Concurrency-safe: relies on the ``uq_phone_daily_stats`` unique
        constraint. If the row already exists the insert is a no-op.
        """
        stmt = (
            pg_insert(PhoneNumberDailyStats)
            .values(
                phone_number_id=phone_number_id,
                date=stats_date,
            )
            .on_conflict_do_nothing(
                index_elements=["phone_number_id", "date"],
            )
        )
        await db.execute(stmt)

    async def _atomic_increment(
        self,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
        **column_deltas: int,
    ) -> None:
        """Atomically increment one or more counters on today's stats row.

        Uses an in-database ``UPDATE ... SET col = col + delta`` so that
        concurrent webhook handlers and worker sends cannot lose increments
        the way a Python-side read-modify-write would.
        """
        stats_date = datetime.now(UTC).date()
        await self._ensure_daily_stats_row(phone_number_id, stats_date, db)

        values = {
            column: getattr(PhoneNumberDailyStats, column) + delta
            for column, delta in column_deltas.items()
        }
        await db.execute(
            update(PhoneNumberDailyStats)
            .where(
                and_(
                    PhoneNumberDailyStats.phone_number_id == phone_number_id,
                    PhoneNumberDailyStats.date == stats_date,
                )
            )
            .values(**values)
        )
        await db.flush()

    async def increment_sent(
        self,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Increment messages sent counter.

        Args:
            phone_number_id: Phone number UUID
            db: Database session
        """
        await self._atomic_increment(phone_number_id, db, messages_sent=1)

    async def increment_delivered(
        self,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Increment messages delivered counter.

        Args:
            phone_number_id: Phone number UUID
            db: Database session
        """
        await self._atomic_increment(phone_number_id, db, messages_delivered=1)

    async def increment_hard_bounce(
        self,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Increment hard bounce counter.

        Args:
            phone_number_id: Phone number UUID
            db: Database session
        """
        await self._atomic_increment(
            phone_number_id, db, hard_bounces=1, messages_failed=1
        )

    async def increment_soft_bounce(
        self,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Increment soft bounce counter.

        Args:
            phone_number_id: Phone number UUID
            db: Database session
        """
        await self._atomic_increment(
            phone_number_id, db, soft_bounces=1, messages_failed=1
        )

    async def increment_spam_complaint(
        self,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Increment spam complaint counter.

        Args:
            phone_number_id: Phone number UUID
            db: Database session
        """
        await self._atomic_increment(
            phone_number_id, db, spam_complaints=1, messages_failed=1
        )

    async def increment_opt_out(
        self,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Increment opt-out counter.

        Args:
            phone_number_id: Phone number UUID
            db: Database session
        """
        await self._atomic_increment(phone_number_id, db, opt_outs=1)

    async def release_from_quarantine(
        self,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
        start_warming: bool = True,
    ) -> bool:
        """Release a phone number from quarantine.

        Args:
            phone_number_id: Phone number UUID
            db: Database session
            start_warming: Whether to start warming schedule after release

        Returns:
            True if released successfully
        """
        result = await db.execute(
            select(PhoneNumber).where(PhoneNumber.id == phone_number_id)
        )
        phone = result.scalar_one_or_none()

        if not phone:
            return False

        if phone.health_status != PhoneNumberHealthStatus.QUARANTINED:
            return False

        phone.quarantine_reviewed = True

        if start_warming:
            # Start warming schedule to gradually rebuild reputation
            phone.health_status = PhoneNumberHealthStatus.WARMING
            phone.warming_stage = 1
            phone.warming_started_at = datetime.now(UTC)
        else:
            phone.health_status = PhoneNumberHealthStatus.HEALTHY

        await db.commit()

        self.logger.info(
            "number_released_from_quarantine",
            phone_number_id=str(phone_number_id),
            phone_number=phone.phone_number,
            start_warming=start_warming,
        )

        return True

    async def get_reputation_summary(
        self,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Get reputation summary for a phone number.

        Args:
            phone_number_id: Phone number UUID
            db: Database session

        Returns:
            Dictionary with reputation metrics
        """
        result = await db.execute(
            select(PhoneNumber).where(PhoneNumber.id == phone_number_id)
        )
        phone = result.scalar_one_or_none()

        if not phone:
            return {}

        return {
            "phone_number": phone.phone_number,
            "health_status": phone.health_status,
            "trust_tier": phone.trust_tier,
            "messages_sent_7d": phone.messages_sent_7d,
            "messages_delivered_7d": phone.messages_delivered_7d,
            "delivery_rate": round(phone.delivery_rate * 100, 2),
            "bounce_rate": round(phone.bounce_rate * 100, 2),
            "complaint_rate": round(phone.complaint_rate * 100, 4),
            "hard_bounces_7d": phone.hard_bounces_7d,
            "soft_bounces_7d": phone.soft_bounces_7d,
            "spam_complaints_7d": phone.spam_complaints_7d,
            "opt_outs_7d": phone.opt_outs_7d,
            "warming_stage": phone.warming_stage,
            "quarantine_reason": phone.quarantine_reason,
            "thresholds": {
                "max_bounce_rate": self.MAX_BOUNCE_RATE * 100,
                "max_complaint_rate": self.MAX_COMPLAINT_RATE * 100,
                "min_delivery_rate": self.MIN_DELIVERY_RATE * 100,
            },
        }
