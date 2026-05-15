"""Base campaign worker with shared logic for SMS and voice campaign workers.

Extracts common patterns from campaign_worker.py and voice_campaign_worker.py:
- Polling for running campaigns filtered by type
- Sending hours and scheduled end checks
- Campaign completion detection with report generation
"""

from abc import abstractmethod
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute, selectinload

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.campaign import (
    Campaign,
    CampaignContact,
    CampaignStatus,
    CampaignType,
)
from app.services.ai.campaign_report_service import CampaignReportService
from app.workers.base import BaseWorker
from app.workers.retryable import RetryableWorker


class BaseCampaignWorker(RetryableWorker, BaseWorker):
    """Abstract base for campaign workers (SMS and voice).

    Subclasses must implement:
    - campaign_type: Which CampaignType to process
    - eager_loads: SQLAlchemy selectinload options for the campaign query
    - _process_campaign_contacts(): The actual contact processing logic
    - _get_remaining_filter(): SQLAlchemy WHERE clause for remaining contacts
    """

    max_retries = 3
    backoff_base_seconds = 2.0

    @property
    @abstractmethod
    def campaign_type(self) -> CampaignType:
        """The campaign type this worker processes."""

    @property
    @abstractmethod
    def eager_loads(self) -> list[QueryableAttribute[Any]]:
        """SQLAlchemy selectinload options for the campaign query."""

    @abstractmethod
    async def _process_campaign_contacts(
        self,
        campaign: Campaign,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Process contacts for a campaign.

        Subclasses handle service creation, processing, calling
        self._check_completion(), committing, and service cleanup.
        """

    @abstractmethod
    def _get_remaining_filter(self, campaign: Campaign) -> Any:
        """Return a SQLAlchemy WHERE clause for contacts still remaining."""

    async def _process_items(self) -> None:
        """Process all running campaigns of this worker's type."""
        async with AsyncSessionLocal() as db:
            query = (
                select(Campaign)
                .options(*[selectinload(load) for load in self.eager_loads])
                .where(
                    and_(
                        Campaign.status == CampaignStatus.RUNNING,
                        Campaign.campaign_type == self.campaign_type.value,
                    )
                )
            )
            result = await db.execute(query)
            campaigns = result.scalars().all()

            if not campaigns:
                return

            self.logger.debug("Processing campaigns", count=len(campaigns))

            for campaign in campaigns:
                await self.execute_with_retry(
                    self._process_campaign,
                    campaign,
                    db,
                    item_key=f"campaign:{campaign.id}",
                )

    async def _process_campaign(
        self, campaign: Campaign, db: AsyncSession
    ) -> None:
        """Process a single campaign with common checks then delegate."""
        log = self.logger.bind(
            campaign_id=str(campaign.id),
            campaign_name=campaign.name,
        )

        if not self._is_within_sending_hours(campaign):
            log.debug("Outside sending hours")
            return

        if campaign.scheduled_end and datetime.now(UTC) > campaign.scheduled_end:
            log.info("Campaign scheduled end reached, completing")
            campaign.status = CampaignStatus.COMPLETED
            campaign.completed_at = datetime.now(UTC)
            await db.commit()
            return

        if not settings.telnyx_api_key:
            log.warning("No Telnyx API key configured")
            return

        await self._process_campaign_contacts(campaign, db, log)

    def _is_within_sending_hours(self, campaign: Campaign) -> bool:
        """Check if current time is within campaign sending hours."""
        if campaign.sending_hours_start is None or campaign.sending_hours_end is None:
            self.logger.debug(
                "Sending hours not set, allowing",
                start=campaign.sending_hours_start,
                end=campaign.sending_hours_end,
            )
            return True

        tz = ZoneInfo(campaign.timezone or "UTC")
        now = datetime.now(tz)

        if campaign.sending_days and now.weekday() not in campaign.sending_days:
            self.logger.debug(
                "Not a sending day",
                sending_days=campaign.sending_days,
                weekday=now.weekday(),
            )
            return False

        start_val = campaign.sending_hours_start
        end_val = campaign.sending_hours_end
        start_time: time = start_val.time() if isinstance(start_val, datetime) else start_val
        end_time: time = end_val.time() if isinstance(end_val, datetime) else end_val
        current_time = now.time()

        result = start_time <= current_time <= end_time
        self.logger.debug(
            "Sending hours check",
            start_time=str(start_time),
            end_time=str(end_time),
            current_time=str(current_time),
            result=result,
        )
        return result

    async def _check_completion(
        self,
        campaign: Campaign,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Check if campaign is complete based on remaining contacts."""
        remaining_result = await db.execute(
            select(func.count(CampaignContact.id)).where(
                self._get_remaining_filter(campaign)
            )
        )
        remaining = remaining_result.scalar() or 0

        if remaining == 0:
            log.info("All contacts processed, completing campaign")
            campaign.status = CampaignStatus.COMPLETED
            campaign.completed_at = datetime.now(UTC)

            try:
                service = CampaignReportService()
                await service.generate_report(db, campaign.id)
                log.info("Campaign post-mortem report generated")
            except Exception:
                log.warning("Failed to generate post-mortem report", exc_info=True)
