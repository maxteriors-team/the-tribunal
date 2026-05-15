"""Voice campaign worker service for processing voice campaigns with SMS fallback.

This background worker:
1. Polls for running voice campaigns
2. Checks sending hours and rate limits
3. Gets pending contacts and initiates calls
4. Tracks call outcomes via webhook handlers
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute, selectinload

from app.core.config import settings
from app.models.campaign import (
    Campaign,
    CampaignContact,
    CampaignContactStatus,
    CampaignType,
)
from app.services.telephony.telnyx_voice import TelnyxVoiceService
from app.workers.base import WorkerRegistry
from app.workers.base_campaign_worker import BaseCampaignWorker

# Worker configuration - more conservative for voice
MAX_CALLS_PER_TICK = 5


class VoiceCampaignWorker(BaseCampaignWorker):
    """Background worker for processing voice campaigns."""

    POLL_INTERVAL_SECONDS = 10
    COMPONENT_NAME = "voice_campaign_worker"
    max_retries = 3
    backoff_base_seconds = 2.0

    def __init__(self) -> None:
        super().__init__()
        self._rate_trackers: dict[str, list[datetime]] = {}

    @property
    def campaign_type(self) -> CampaignType:
        return CampaignType.VOICE_SMS_FALLBACK

    @property
    def eager_loads(self) -> list[QueryableAttribute[Any]]:
        return [Campaign.voice_agent, Campaign.sms_fallback_agent]

    def _get_remaining_filter(self, campaign: Campaign) -> Any:
        return and_(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status.in_([
                CampaignContactStatus.PENDING,
                CampaignContactStatus.CALLING,
            ]),
        )

    async def _process_campaign_contacts(
        self,
        campaign: Campaign,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Process voice campaign contacts: clean up stuck calls and initiate new ones."""
        voice_service = TelnyxVoiceService(settings.telnyx_api_key)
        try:
            await self._cleanup_stuck_calls(campaign, db, log)
            await self._process_pending_calls(campaign, voice_service, db, log)
            await self._check_completion(campaign, db, log)
            await db.commit()
        finally:
            await voice_service.close()

    async def _process_pending_calls(
        self,
        campaign: Campaign,
        voice_service: TelnyxVoiceService,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Initiate calls to pending contacts."""
        available_slots = self._get_available_call_slots(campaign)
        if available_slots <= 0:
            log.debug("Rate limit reached for this minute")
            return

        calls_to_make = min(available_slots, MAX_CALLS_PER_TICK)

        # Get pending contacts with row-level locking
        pending_result = await db.execute(
            select(CampaignContact)
            .options(selectinload(CampaignContact.contact))
            .where(
                and_(
                    CampaignContact.campaign_id == campaign.id,
                    CampaignContact.status == CampaignContactStatus.PENDING,
                    CampaignContact.opted_out.is_(False),
                )
            )
            .order_by(
                CampaignContact.priority.desc(),
                CampaignContact.created_at,
            )
            .limit(calls_to_make)
            .with_for_update(skip_locked=True)
        )
        pending_contacts = pending_result.scalars().all()

        if not pending_contacts:
            return

        log.info(
            "Initiating calls",
            count=len(pending_contacts),
            available_slots=available_slots,
        )

        # Build webhook URL
        api_base = settings.api_base_url or "http://localhost:8000"
        webhook_url = f"{api_base}/webhooks/telnyx/voice"

        # Get connection ID from settings or campaign (None = auto-discover)
        connection_id = campaign.voice_connection_id or settings.telnyx_connection_id

        for campaign_contact in pending_contacts:
            contact = campaign_contact.contact
            if not contact or not contact.phone_number:
                log.warning(
                    "Contact missing phone number",
                    contact_id=campaign_contact.contact_id,
                )
                campaign_contact.status = CampaignContactStatus.FAILED
                campaign_contact.last_error = "missing_phone_number"
                continue

            try:
                # Initiate call
                message = await voice_service.initiate_call(
                    to_number=contact.phone_number,
                    from_number=campaign.from_phone_number,
                    connection_id=connection_id,
                    webhook_url=webhook_url,
                    db=db,
                    workspace_id=campaign.workspace_id,
                    contact_phone=contact.phone_number,
                    agent_id=campaign.voice_agent_id,
                    enable_machine_detection=campaign.enable_machine_detection,
                    campaign_id=campaign.id,
                )

                # Update campaign contact
                campaign_contact.status = CampaignContactStatus.CALLING
                campaign_contact.call_attempts += 1
                campaign_contact.last_call_at = datetime.now(UTC)
                campaign_contact.call_message_id = message.id

                # Update campaign stats
                campaign.calls_attempted += 1

                # Track rate limiting
                self._track_call_made(str(campaign.id))

                log.info(
                    "Call initiated",
                    contact_id=contact.id,
                    phone=contact.phone_number,
                    message_id=str(message.id),
                    call_attempt=campaign_contact.call_attempts,
                )

            except Exception as e:
                log.exception(
                    "Failed to initiate call",
                    contact_id=contact.id,
                    phone=contact.phone_number,
                    error=str(e),
                )
                campaign_contact.status = CampaignContactStatus.FAILED
                campaign_contact.last_error = str(e)
                campaign.error_count += 1
                campaign.last_error = str(e)
                campaign.last_error_at = datetime.now(UTC)

    async def _cleanup_stuck_calls(
        self,
        campaign: Campaign,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Clean up contacts stuck in 'calling' status when webhooks never arrive.

        If a contact has been in 'calling' status for more than 5 minutes,
        mark it as 'call_failed' so the campaign can complete.
        """
        stuck_timeout = timedelta(minutes=5)
        cutoff_time = datetime.now(UTC) - stuck_timeout

        # Find contacts stuck in calling status
        stuck_result = await db.execute(
            select(CampaignContact)
            .where(
                and_(
                    CampaignContact.campaign_id == campaign.id,
                    CampaignContact.status == CampaignContactStatus.CALLING,
                    CampaignContact.last_call_at < cutoff_time,
                )
            )
        )
        stuck_contacts = stuck_result.scalars().all()

        if not stuck_contacts:
            return

        log.warning(
            "cleaning_up_stuck_calls",
            count=len(stuck_contacts),
            timeout_minutes=5,
        )

        for contact in stuck_contacts:
            contact.status = CampaignContactStatus.CALL_FAILED
            contact.last_call_status = "no_answer"
            contact.last_error = "Call webhook timeout - no response after 5 minutes"
            campaign.calls_no_answer += 1

        log.info("stuck_calls_cleaned_up", count=len(stuck_contacts))

    def _get_available_call_slots(self, campaign: Campaign) -> int:
        """Calculate how many calls can be made based on rate limit."""
        campaign_id = str(campaign.id)
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=1)

        if campaign_id in self._rate_trackers:
            self._rate_trackers[campaign_id] = [
                call_time
                for call_time in self._rate_trackers[campaign_id]
                if call_time > cutoff
            ]
            calls_in_last_minute = len(self._rate_trackers[campaign_id])
        else:
            calls_in_last_minute = 0

        return max(0, campaign.calls_per_minute - calls_in_last_minute)

    def _track_call_made(self, campaign_id: str) -> None:
        """Track a call for rate limiting."""
        if campaign_id not in self._rate_trackers:
            self._rate_trackers[campaign_id] = []
        self._rate_trackers[campaign_id].append(datetime.now(UTC))


# Singleton registry
_registry = WorkerRegistry(VoiceCampaignWorker)
start_voice_campaign_worker = _registry.start
stop_voice_campaign_worker = _registry.stop
get_voice_campaign_worker = _registry.get
