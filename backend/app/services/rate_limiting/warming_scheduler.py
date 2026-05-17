"""Phone number warming schedule management."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phone_number import PhoneNumber, PhoneNumberHealthStatus

logger = structlog.get_logger()


class WarmingScheduler:
    """Manage phone number warming schedules.

    New phone numbers should be "warmed" by gradually increasing
    daily send limits over 7 days to build carrier reputation.
    """

    # 7-day warming schedule: stage -> max daily messages
    WARMING_SCHEDULE: dict[int, int] = {
        1: 10,  # Day 1: 10 messages max
        2: 25,  # Day 2: 25 messages
        3: 50,  # Day 3: 50 messages
        4: 100,  # Day 4: 100 messages
        5: 200,  # Day 5: 200 messages
        6: 400,  # Day 6: 400 messages
        7: 800,  # Day 7: 800 messages
        # After day 7, use full daily_limit
    }

    def __init__(self) -> None:
        self.logger = logger.bind(component="warming_scheduler")

    def get_warming_daily_limit(self, phone: PhoneNumber) -> int:
        """Get current daily limit based on warming stage.

        Args:
            phone: Phone number model

        Returns:
            Maximum messages allowed for the day
        """
        if phone.warming_stage == 0:
            # Not warming, use full limit
            return phone.daily_limit

        if phone.warming_stage > 7:
            # Warming complete
            return phone.daily_limit

        # Return warming limit for current stage
        return self.WARMING_SCHEDULE.get(phone.warming_stage, phone.daily_limit)

    async def start_warming(
        self,
        phone: PhoneNumber,
        db: AsyncSession,
    ) -> None:
        """Start warming schedule for a phone number.

        Args:
            phone: Phone number model
            db: Database session
        """
        phone.warming_stage = 1
        phone.warming_started_at = datetime.now(UTC)
        phone.health_status = PhoneNumberHealthStatus.WARMING

        await db.commit()

        self.logger.info(
            "warming_started",
            phone_number=phone.phone_number,
            phone_number_id=str(phone.id),
            daily_limit=self.get_warming_daily_limit(phone),
        )

    async def advance_warming_stage(
        self,
        phone: PhoneNumber,
        db: AsyncSession,
    ) -> bool:
        """Advance warming stage if 24 hours have passed.

        Args:
            phone: Phone number model
            db: Database session

        Returns:
            True if stage was advanced
        """
        if phone.warming_stage == 0 or not phone.warming_started_at:
            return False

        now = datetime.now(UTC)

        # Calculate days elapsed since warming started
        days_elapsed = (now - phone.warming_started_at).days

        # Only advance if enough days have passed
        if days_elapsed >= phone.warming_stage:
            if phone.warming_stage >= 7:
                # Warming complete
                phone.warming_stage = 0
                phone.health_status = PhoneNumberHealthStatus.HEALTHY

                self.logger.info(
                    "warming_completed",
                    phone_number=phone.phone_number,
                    phone_number_id=str(phone.id),
                )
            else:
                phone.warming_stage += 1
                new_limit = self.get_warming_daily_limit(phone)

                self.logger.info(
                    "warming_stage_advanced",
                    phone_number=phone.phone_number,
                    phone_number_id=str(phone.id),
                    new_stage=phone.warming_stage,
                    new_daily_limit=new_limit,
                )

            await db.commit()
            return True

        return False

    async def reset_warming(
        self,
        phone: PhoneNumber,
        db: AsyncSession,
    ) -> None:
        """Reset warming schedule (e.g., after quarantine release).

        Args:
            phone: Phone number model
            db: Database session
        """
        phone.warming_stage = 1
        phone.warming_started_at = datetime.now(UTC)
        phone.health_status = PhoneNumberHealthStatus.WARMING

        await db.commit()

        self.logger.info(
            "warming_reset",
            phone_number=phone.phone_number,
            phone_number_id=str(phone.id),
        )

    def get_warming_progress(self, phone: PhoneNumber) -> dict[str, int | float | bool]:
        """Get warming progress information.

        Args:
            phone: Phone number model

        Returns:
            Dictionary with warming progress info
        """
        if phone.warming_stage == 0:
            return {
                "is_warming": False,
                "stage": 0,
                "days_remaining": 0,
                "current_limit": phone.daily_limit,
                "final_limit": phone.daily_limit,
                "progress_percent": 100.0,
            }

        days_remaining = max(0, 7 - phone.warming_stage)
        progress_percent = (phone.warming_stage / 7) * 100

        return {
            "is_warming": True,
            "stage": phone.warming_stage,
            "days_remaining": days_remaining,
            "current_limit": self.get_warming_daily_limit(phone),
            "final_limit": phone.daily_limit,
            "progress_percent": round(progress_percent, 1),
        }

    async def start_warming_for_all_numbers(
        self,
        phone_number_ids: list[uuid.UUID],
        db: AsyncSession,
    ) -> int:
        """Start warming for multiple phone numbers.

        Args:
            phone_number_ids: List of phone number IDs to warm
            db: Database session

        Returns:
            Number of phone numbers started warming
        """
        from sqlalchemy import select

        count = 0
        for phone_id in phone_number_ids:
            result = await db.execute(select(PhoneNumber).where(PhoneNumber.id == phone_id))
            phone = result.scalar_one_or_none()

            if phone and phone.warming_stage == 0:
                await self.start_warming(phone, db)
                count += 1

        return count
