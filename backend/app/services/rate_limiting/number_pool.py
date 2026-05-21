"""Phone number pool management for campaigns."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.campaign import Campaign
from app.models.campaign_number_pool import CampaignNumberPool
from app.models.message_test import MessageTest
from app.models.phone_number import PhoneNumber, PhoneNumberHealthStatus
from app.services.rate_limiting.rate_limiter import RateLimiter
from app.services.rate_limiting.warming_scheduler import WarmingScheduler

logger = structlog.get_logger()


class NumberPoolManager:
    """Manages phone number pooling and rotation for campaigns.

    Implements strict round-robin selection with health awareness:
    - Filters by health status (healthy, warming only)
    - Checks all rate limits before selection
    - Orders by priority DESC, then last_used_at ASC (round-robin)
    """

    def __init__(self) -> None:
        self.logger = logger.bind(component="number_pool")
        self.rate_limiter = RateLimiter()
        self.warming_scheduler = WarmingScheduler()

    async def get_next_available_number(
        self,
        campaign: Campaign,
        db: AsyncSession,
        consume_rate_limit: bool = True,
    ) -> PhoneNumber | None:
        """Get next available number from campaign pool using strict round-robin.

        Selection algorithm:
        1. If use_number_pool=False, return single from_phone_number (legacy)
        2. Filter numbers by health_status (healthy, warming only)
        3. Order by priority DESC, then last_used_at ASC (round-robin)
        4. Check rate limits for each number until one passes
        5. Return None if no numbers available (campaign should pause)

        Args:
            campaign: Campaign model
            db: Database session

        Returns:
            Available phone number, or None if all rate limited
        """
        log = self.logger.bind(campaign_id=str(campaign.id))

        # Legacy mode: single number per campaign
        if not campaign.use_number_pool:
            result = await db.execute(
                select(PhoneNumber).where(PhoneNumber.phone_number == campaign.from_phone_number)
            )
            phone = result.scalar_one_or_none()

            if phone and await self._phone_has_capacity(phone):
                if consume_rate_limit and not await self.reserve_number_for_send(phone, db):
                    log.debug("single_number_rate_limited", phone=campaign.from_phone_number)
                    return None
                return phone

            log.debug("single_number_rate_limited", phone=campaign.from_phone_number)
            return None

        # Pool mode: select from campaign's number pool
        pool_result = await db.execute(
            select(CampaignNumberPool)
            .options(selectinload(CampaignNumberPool.phone_number))
            .where(
                and_(
                    CampaignNumberPool.campaign_id == campaign.id,
                    CampaignNumberPool.is_active.is_(True),
                )
            )
            .order_by(
                CampaignNumberPool.priority.desc(),
                CampaignNumberPool.last_used_at.asc().nullsfirst(),
            )
        )
        pool_entries = pool_result.scalars().all()

        if not pool_entries:
            log.warning("no_numbers_in_pool")
            return None

        # Try each number in pool (round-robin order)
        for pool_entry in pool_entries:
            phone = pool_entry.phone_number

            # Skip inactive or non-SMS numbers
            if not phone or not phone.is_active or not phone.sms_enabled:
                continue

            # Skip quarantined or cooldown numbers
            if phone.health_status not in [
                PhoneNumberHealthStatus.HEALTHY.value,
                PhoneNumberHealthStatus.WARMING.value,
            ]:
                log.debug(
                    "skipping_unhealthy_number",
                    phone=phone.phone_number,
                    health=phone.health_status,
                )
                continue

            # Check if warming limit would be exceeded
            if phone.warming_stage > 0:
                warming_limit = self.warming_scheduler.get_warming_daily_limit(phone)
                counts = await self.rate_limiter.get_current_counts(phone.id)
                if counts["daily"] >= warming_limit:
                    log.debug(
                        "warming_limit_reached",
                        phone=phone.phone_number,
                        stage=phone.warming_stage,
                        limit=warming_limit,
                    )
                    continue

            # Check all rate limits without consuming counters unless requested.
            if await self._phone_has_capacity(phone):
                if consume_rate_limit and not await self.reserve_number_for_send(phone, db):
                    continue

                if consume_rate_limit:
                    pool_entry.last_used_at = datetime.now(UTC)
                    pool_entry.messages_sent += 1
                    await db.flush()

                log.info(
                    "selected_number_from_pool",
                    phone=phone.phone_number,
                    health=phone.health_status,
                    priority=pool_entry.priority,
                    consume_rate_limit=consume_rate_limit,
                )
                return phone

        log.warning("all_numbers_rate_limited")
        return None

    async def peek_next_available_number(
        self,
        campaign: Campaign,
        db: AsyncSession,
    ) -> PhoneNumber | None:
        """Get the next number with capacity without consuming Redis counters."""
        return await self.get_next_available_number(campaign, db, consume_rate_limit=False)

    async def reserve_number_for_send(self, phone: PhoneNumber, db: AsyncSession) -> bool:
        """Consume send counters for a selected phone number immediately before send."""
        if not await self._check_all_rate_limits(phone):
            return False

        pool_result = await db.execute(
            select(CampaignNumberPool).where(CampaignNumberPool.phone_number_id == phone.id)
        )
        for pool_entry in pool_result.scalars().all():
            pool_entry.last_used_at = datetime.now(UTC)
            pool_entry.messages_sent += 1
        await db.flush()
        return True

    async def _phone_has_capacity(self, phone: PhoneNumber) -> bool:
        counts = await self.rate_limiter.get_current_counts(phone.id)
        if counts["hourly"] >= phone.hourly_limit:
            return False
        return counts["daily"] < phone.daily_limit

    async def _check_all_rate_limits(self, phone: PhoneNumber) -> bool:
        """Check if phone number passes all rate limits and consume counters."""
        if not await self.rate_limiter.check_and_increment_per_second(
            phone.id, phone.messages_per_second
        ):
            return False

        hourly_ok, _ = await self.rate_limiter.check_and_increment_hourly(
            phone.id, phone.hourly_limit
        )
        if not hourly_ok:
            return False

        daily_ok, _ = await self.rate_limiter.check_and_increment_daily(phone.id, phone.daily_limit)
        return daily_ok

    async def add_number_to_campaign_pool(
        self,
        campaign_id: uuid.UUID,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
        priority: int = 0,
    ) -> CampaignNumberPool:
        """Add phone number to campaign pool.

        Args:
            campaign_id: Campaign UUID
            phone_number_id: Phone number UUID
            db: Database session
            priority: Priority level (higher = preferred)

        Returns:
            Created pool entry
        """
        # Check if already exists
        existing = await db.execute(
            select(CampaignNumberPool).where(
                and_(
                    CampaignNumberPool.campaign_id == campaign_id,
                    CampaignNumberPool.phone_number_id == phone_number_id,
                )
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("Phone number already in campaign pool")

        pool_entry = CampaignNumberPool(
            campaign_id=campaign_id,
            phone_number_id=phone_number_id,
            priority=priority,
        )
        db.add(pool_entry)
        await db.commit()
        await db.refresh(pool_entry)

        self.logger.info(
            "number_added_to_pool",
            campaign_id=str(campaign_id),
            phone_number_id=str(phone_number_id),
            priority=priority,
        )

        return pool_entry

    async def remove_number_from_pool(
        self,
        campaign_id: uuid.UUID,
        phone_number_id: uuid.UUID,
        db: AsyncSession,
    ) -> bool:
        """Remove phone number from campaign pool.

        Args:
            campaign_id: Campaign UUID
            phone_number_id: Phone number UUID
            db: Database session

        Returns:
            True if removed
        """
        result = await db.execute(
            select(CampaignNumberPool).where(
                and_(
                    CampaignNumberPool.campaign_id == campaign_id,
                    CampaignNumberPool.phone_number_id == phone_number_id,
                )
            )
        )
        pool_entry = result.scalar_one_or_none()

        if pool_entry:
            await db.delete(pool_entry)
            await db.commit()

            self.logger.info(
                "number_removed_from_pool",
                campaign_id=str(campaign_id),
                phone_number_id=str(phone_number_id),
            )
            return True

        return False

    async def update_pool_priority(
        self,
        campaign_id: uuid.UUID,
        phone_number_id: uuid.UUID,
        priority: int,
        db: AsyncSession,
    ) -> bool:
        """Update priority of a number in the pool.

        Args:
            campaign_id: Campaign UUID
            phone_number_id: Phone number UUID
            priority: New priority level
            db: Database session

        Returns:
            True if updated
        """
        result = await db.execute(
            select(CampaignNumberPool).where(
                and_(
                    CampaignNumberPool.campaign_id == campaign_id,
                    CampaignNumberPool.phone_number_id == phone_number_id,
                )
            )
        )
        pool_entry = result.scalar_one_or_none()

        if pool_entry:
            pool_entry.priority = priority
            await db.commit()
            return True

        return False

    async def get_pool_status(
        self,
        campaign_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Get status of all numbers in campaign pool.

        Args:
            campaign_id: Campaign UUID
            db: Database session

        Returns:
            List of pool entry statuses
        """
        result = await db.execute(
            select(CampaignNumberPool)
            .options(selectinload(CampaignNumberPool.phone_number))
            .where(CampaignNumberPool.campaign_id == campaign_id)
            .order_by(
                CampaignNumberPool.priority.desc(),
                CampaignNumberPool.last_used_at.asc().nullsfirst(),
            )
        )
        pool_entries = result.scalars().all()

        statuses = []
        for entry in pool_entries:
            phone = entry.phone_number
            counts = await self.rate_limiter.get_current_counts(phone.id)

            statuses.append(
                {
                    "phone_number": phone.phone_number,
                    "phone_number_id": str(phone.id),
                    "priority": entry.priority,
                    "is_active": entry.is_active,
                    "messages_sent": entry.messages_sent,
                    "last_used_at": entry.last_used_at.isoformat() if entry.last_used_at else None,
                    "health_status": phone.health_status,
                    "hourly_used": counts["hourly"],
                    "hourly_limit": phone.hourly_limit,
                    "daily_used": counts["daily"],
                    "daily_limit": phone.daily_limit,
                    "warming_stage": phone.warming_stage,
                }
            )

        return statuses

    async def enable_pool_for_campaign(
        self,
        campaign_id: uuid.UUID,
        phone_number_ids: list[uuid.UUID],
        db: AsyncSession,
    ) -> int:
        """Enable number pooling for a campaign and add numbers.

        Args:
            campaign_id: Campaign UUID
            phone_number_ids: List of phone number UUIDs to add
            db: Database session

        Returns:
            Number of phone numbers added
        """
        # Enable pool mode on campaign
        result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
        campaign = result.scalar_one_or_none()

        if not campaign:
            raise ValueError("Campaign not found")

        campaign.use_number_pool = True

        # Add numbers to pool
        count = 0
        for i, phone_id in enumerate(phone_number_ids):
            try:
                await self.add_number_to_campaign_pool(
                    campaign_id=campaign_id,
                    phone_number_id=phone_id,
                    db=db,
                    priority=len(phone_number_ids) - i,  # First number = highest priority
                )
                count += 1
            except ValueError:
                # Already exists
                pass

        await db.commit()

        self.logger.info(
            "pool_enabled_for_campaign",
            campaign_id=str(campaign_id),
            numbers_added=count,
        )

        return count

    async def get_next_available_number_for_test(
        self,
        test: MessageTest,
        db: AsyncSession,
    ) -> PhoneNumber | None:
        """Get next available number for a message test.

        For simplicity, message tests use the single from_phone_number approach.
        If use_number_pool is True, falls back to selecting any active workspace number.

        Args:
            test: MessageTest model
            db: Database session

        Returns:
            Available phone number, or None if all rate limited
        """
        log = self.logger.bind(test_id=str(test.id))

        # Get the phone number configured for the test
        result = await db.execute(
            select(PhoneNumber).where(PhoneNumber.phone_number == test.from_phone_number)
        )
        phone = result.scalar_one_or_none()

        if phone and await self._check_all_rate_limits(phone):
            return phone

        log.debug("test_number_rate_limited", phone=test.from_phone_number)
        return None
