"""Campaign worker service for processing SMS campaigns.

This background worker:
1. Polls for running campaigns
2. Checks sending hours and rate limits (via Redis)
3. Gets pending contacts and sends initial messages
4. Handles follow-up messages
5. Updates campaign contact status and statistics
6. Supports number pooling and rotation
7. Enforces global opt-out list
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute, selectinload

from app.core.config import settings
from app.models.campaign import (
    Campaign,
    CampaignContact,
    CampaignContactStatus,
    CampaignType,
)
from app.models.contact import Contact
from app.models.offer import Offer
from app.models.phone_number import PhoneNumber
from app.services.compliance.outbound_compliance import (
    OutboundComplianceRequest,
    OutboundComplianceResult,
    OutboundComplianceService,
)
from app.services.idempotency import derive_outbound_key
from app.services.rate_limiting.number_pool import NumberPoolManager
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.rate_limiting.rate_limiter import RateLimiter
from app.services.rate_limiting.reputation_tracker import ReputationTracker
from app.services.rate_limiting.warming_scheduler import WarmingScheduler
from app.services.telephony.text_provider import TextMessageProvider, get_text_message_provider
from app.workers.base import WorkerRegistry
from app.workers.base_campaign_worker import BaseCampaignWorker

logger = structlog.get_logger()

# Worker configuration
MAX_MESSAGES_PER_TICK = 20
TextProviderCache = dict[tuple[str | None, str | None], TextMessageProvider]


def _preferred_provider_for_phone(phone_number: PhoneNumber) -> str | None:
    """Keep campaign sends on the selected sender identity's transport."""
    if phone_number.imessage_enabled:
        return "mac_relay"
    return None


def _sender_address_for_phone(phone_number: PhoneNumber) -> str:
    """Return the provider-facing sender identity for a campaign sender row."""
    if phone_number.imessage_enabled and phone_number.mac_relay_sender_id:
        return phone_number.mac_relay_sender_id
    return phone_number.phone_number


def _campaign_channel_for_phone(phone_number: PhoneNumber) -> str:
    """Return the campaign compliance/logging channel for the selected sender."""
    if phone_number.imessage_enabled:
        return "imessage"
    return "sms"


class CampaignWorker(BaseCampaignWorker):
    """Background worker for processing SMS campaigns."""

    POLL_INTERVAL_SECONDS = settings.campaign_poll_interval
    COMPONENT_NAME = "campaign_worker"
    # Per-cycle the worker sends up to MAX_MESSAGES_PER_TICK SMS; cap matches
    # so a full tick can fan out without exceeding the per-number rate limit
    # enforced downstream by the rate-limiting service.
    MAX_CONCURRENCY = 10
    max_retries = 3
    backoff_base_seconds = 2.0
    requires_telnyx_api_key = False

    def __init__(self) -> None:
        super().__init__()
        # Rate limiting services (Redis-based)
        self.number_pool = NumberPoolManager()
        self.rate_limiter = RateLimiter()
        self.opt_out_manager = OptOutManager()
        self.compliance_service = OutboundComplianceService(self.opt_out_manager)
        self.warming_scheduler = WarmingScheduler()
        self.reputation_tracker = ReputationTracker()

    @property
    def campaign_type(self) -> CampaignType:
        return CampaignType.SMS

    @property
    def eager_loads(self) -> list[QueryableAttribute[Any]]:
        return [Campaign.agent, Campaign.offer]

    def _get_remaining_filter(self, campaign: Campaign) -> Any:
        return and_(
            CampaignContact.campaign_id == campaign.id,
            or_(
                CampaignContact.status == CampaignContactStatus.PENDING,
                and_(
                    CampaignContact.next_follow_up_at.is_not(None),
                    CampaignContact.follow_ups_sent < campaign.max_follow_ups,
                ),
            ),
        )

    async def _process_campaign_contacts(
        self,
        campaign: Campaign,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Process SMS/iMessage campaign contacts: send initial messages and follow-ups."""
        text_providers: TextProviderCache = {}
        try:
            await self._process_initial_messages(campaign, text_providers, db, log)

            if campaign.follow_up_enabled:
                await self._process_follow_ups(campaign, text_providers, db, log)

            await self._check_completion(campaign, db, log)

            await db.commit()
        finally:
            for provider in text_providers.values():
                await provider.close()

    def _get_text_provider(
        self,
        phone_number: PhoneNumber,
        text_providers: TextProviderCache,
    ) -> TextMessageProvider:
        """Return a cached provider for the selected sender identity."""
        preferred_provider = _preferred_provider_for_phone(phone_number)
        mac_relay_service = None
        if phone_number.imessage_enabled:
            mac_relay_service = phone_number.mac_relay_service
        cache_key = (preferred_provider, mac_relay_service)
        provider = text_providers.get(cache_key)
        if provider is None:
            provider = get_text_message_provider(
                preferred_provider,
                mac_relay_service=mac_relay_service,
            )
            text_providers[cache_key] = provider
        return provider

    async def _process_initial_messages(  # noqa: PLR0912, PLR0915
        self,
        campaign: Campaign,
        text_providers: TextProviderCache,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Process and send initial messages to pending contacts."""
        # Check campaign-level rate limit (Redis-based)
        campaign_rate_ok = await self.rate_limiter.check_campaign_rate_limit(
            campaign.id, campaign.messages_per_minute
        )
        if not campaign_rate_ok:
            log.debug("Campaign rate limit reached")
            return

        messages_to_send = MAX_MESSAGES_PER_TICK

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
            .limit(messages_to_send)
            .with_for_update(skip_locked=True)
        )
        pending_contacts = pending_result.scalars().all()

        if not pending_contacts:
            return

        log.info(
            "Sending initial messages",
            count=len(pending_contacts),
        )

        sent_count = 0
        conversations_to_assign: list[uuid.UUID] = []
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

            from_phone = await self.number_pool.peek_next_available_number(campaign, db)
            if not from_phone:
                log.warning("No available numbers in pool, pausing sending")
                break

            channel = _campaign_channel_for_phone(from_phone)
            action_type = f"campaign_initial_{channel}"
            compliance_result = await self.compliance_service.evaluate(
                OutboundComplianceRequest(
                    workspace_id=campaign.workspace_id,
                    campaign=campaign,
                    campaign_contact=campaign_contact,
                    contact=contact,
                    channel=channel,
                    action_type=action_type,
                    now=datetime.now(UTC),
                ),
                db,
            )
            self.compliance_service.apply_suppression(
                campaign_contact, compliance_result, datetime.now(UTC)
            )
            if not compliance_result.allowed:
                if compliance_result.reason == "global_opt_out":
                    campaign.contacts_opted_out += 1
                log.info(
                    "compliance_suppressed_campaign_contact",
                    campaign_id=str(campaign.id),
                    campaign_contact_id=str(campaign_contact.id),
                    contact_id=contact.id,
                    reason=compliance_result.reason,
                    action_type=action_type,
                    channel=channel,
                )
                continue

            if campaign.max_messages_per_campaign is not None:
                (
                    cap_ok,
                    campaign_daily_count,
                ) = await self.rate_limiter.check_and_increment_campaign_daily(
                    campaign.id,
                    campaign.max_messages_per_campaign,
                )
                if not cap_ok:
                    cap_result = OutboundComplianceResult(
                        allowed=False,
                        reason="campaign_send_cap_reached",
                        details={"campaign_daily_count": campaign_daily_count},
                    )
                    self.compliance_service.apply_suppression(
                        campaign_contact, cap_result, datetime.now(UTC)
                    )
                    log.info(
                        "compliance_suppressed_campaign_contact",
                        campaign_id=str(campaign.id),
                        campaign_contact_id=str(campaign_contact.id),
                        contact_id=contact.id,
                        reason=cap_result.reason,
                        action_type=action_type,
                        channel=channel,
                    )
                    continue

            if not await self.number_pool.reserve_number_for_send(from_phone, db):
                log.warning("Selected number became rate limited, retrying next tick")
                break

            try:
                # Skip if no initial message template
                if not campaign.initial_message:
                    log.warning("no_initial_message_template", campaign_id=str(campaign.id))
                    campaign_contact.status = CampaignContactStatus.FAILED
                    campaign_contact.last_error = "missing_initial_message"
                    continue

                # Render message template with contact and offer data
                message_text = self._render_template(
                    campaign.initial_message,
                    contact,
                    campaign.offer,
                )

                # Stable per-campaign-contact key for the initial send. A
                # campaign contact only ever sends one initial message, so
                # the campaign_contact id alone is unique.
                initial_key = derive_outbound_key("campaign_sms_initial", campaign_contact.id)

                text_service = self._get_text_provider(from_phone, text_providers)

                # Send via the selected sender's text transport.
                message = await text_service.send_message(
                    to_number=contact.phone_number,
                    from_number=_sender_address_for_phone(from_phone),
                    body=message_text,
                    db=db,
                    workspace_id=campaign.workspace_id,
                    agent_id=campaign.agent_id,
                    phone_number_id=from_phone.id,
                    idempotency_key=initial_key,
                )

                # Update phone number last_sent_at
                from_phone.last_sent_at = datetime.now(UTC)

                # Increment daily stats for the sending phone number
                await self.reputation_tracker.increment_sent(from_phone.id, db)

                # Update contact status and link conversation
                campaign_contact.status = CampaignContactStatus.SENT
                campaign_contact.conversation_id = message.conversation_id
                campaign_contact.messages_sent += 1
                campaign_contact.first_sent_at = campaign_contact.first_sent_at or datetime.now(UTC)
                campaign_contact.last_sent_at = datetime.now(UTC)
                self.record_items_processed()

                # Collect conversation for batch agent assignment after loop
                if campaign.agent_id and message.conversation_id:
                    conversations_to_assign.append(message.conversation_id)

                # Schedule follow-up if enabled
                if campaign.follow_up_enabled and campaign.follow_up_message:
                    campaign_contact.next_follow_up_at = datetime.now(UTC) + timedelta(
                        hours=campaign.follow_up_delay_hours
                    )

                # Update campaign stats
                campaign.messages_sent += 1
                sent_count += 1

                log.info(
                    "Initial message sent",
                    contact_id=contact.id,
                    phone=contact.phone_number,
                    from_phone=from_phone.phone_number,
                    channel=channel,
                    message_id=str(message.id),
                    offer_id=str(campaign.offer_id) if campaign.offer_id else None,
                    has_offer=bool(campaign.offer_id),
                )

            except Exception as e:
                log.exception(
                    "Failed to send initial message",
                    contact_id=contact.id,
                    phone=contact.phone_number,
                    error=str(e),
                )
                campaign_contact.status = CampaignContactStatus.FAILED
                campaign_contact.last_error = str(e)
                campaign.messages_failed += 1
                campaign.error_count += 1
                campaign.last_error = str(e)
                campaign.last_error_at = datetime.now(UTC)

        # Batch-assign campaign agent to all conversations at once
        if conversations_to_assign and campaign.agent_id:
            from sqlalchemy import update

            from app.models.conversation import Conversation

            await db.execute(
                update(Conversation)
                .where(Conversation.id.in_(conversations_to_assign))
                .values(
                    assigned_agent_id=campaign.agent_id,
                    ai_enabled=campaign.ai_enabled,
                )
            )
            log.info(
                "batch_assigned_campaign_agent",
                conversation_count=len(conversations_to_assign),
                agent_id=str(campaign.agent_id),
            )

        if sent_count > 0:
            log.info("Initial messages batch complete", sent=sent_count)

    async def _process_follow_ups(  # noqa: PLR0912, PLR0915
        self,
        campaign: Campaign,
        text_providers: TextProviderCache,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Process and send follow-up messages."""
        if not campaign.follow_up_message:
            return

        # Check campaign-level rate limit
        campaign_rate_ok = await self.rate_limiter.check_campaign_rate_limit(
            campaign.id, campaign.messages_per_minute
        )
        if not campaign_rate_ok:
            return

        now = datetime.now(UTC)
        followup_result = await db.execute(
            select(CampaignContact)
            .options(selectinload(CampaignContact.contact))
            .where(
                and_(
                    CampaignContact.campaign_id == campaign.id,
                    CampaignContact.status.in_(
                        [
                            CampaignContactStatus.SENT,
                            CampaignContactStatus.DELIVERED,
                        ]
                    ),
                    CampaignContact.next_follow_up_at.is_not(None),
                    CampaignContact.next_follow_up_at <= now,
                    CampaignContact.follow_ups_sent < campaign.max_follow_ups,
                    CampaignContact.opted_out.is_(False),
                    CampaignContact.last_reply_at.is_(None),
                )
            )
            .order_by(CampaignContact.next_follow_up_at)
            .limit(MAX_MESSAGES_PER_TICK)
            .with_for_update(skip_locked=True)
        )
        followup_contacts = followup_result.scalars().all()

        # Filter by max messages per contact (0 means unlimited)
        if campaign.max_messages_per_contact > 0:
            followup_contacts = [
                cc
                for cc in followup_contacts
                if cc.messages_sent < campaign.max_messages_per_contact
            ]

        if not followup_contacts:
            return

        log.info("Sending follow-up messages", count=len(followup_contacts))

        sent_count = 0
        for campaign_contact in followup_contacts:
            contact = campaign_contact.contact
            if not contact or not contact.phone_number:
                continue

            from_phone = await self.number_pool.peek_next_available_number(campaign, db)

            if not from_phone:
                log.warning("No available numbers for follow-ups")
                break

            channel = _campaign_channel_for_phone(from_phone)
            action_type = f"campaign_follow_up_{channel}"
            compliance_result = await self.compliance_service.evaluate(
                OutboundComplianceRequest(
                    workspace_id=campaign.workspace_id,
                    campaign=campaign,
                    campaign_contact=campaign_contact,
                    contact=contact,
                    channel=channel,
                    action_type=action_type,
                    now=datetime.now(UTC),
                ),
                db,
            )
            self.compliance_service.apply_suppression(
                campaign_contact, compliance_result, datetime.now(UTC)
            )
            if not compliance_result.allowed:
                if compliance_result.reason == "global_opt_out":
                    campaign.contacts_opted_out += 1
                log.info(
                    "compliance_suppressed_campaign_contact",
                    campaign_id=str(campaign.id),
                    campaign_contact_id=str(campaign_contact.id),
                    contact_id=contact.id,
                    reason=compliance_result.reason,
                    action_type=action_type,
                    channel=channel,
                )
                continue

            if campaign.max_messages_per_campaign is not None:
                (
                    cap_ok,
                    campaign_daily_count,
                ) = await self.rate_limiter.check_and_increment_campaign_daily(
                    campaign.id,
                    campaign.max_messages_per_campaign,
                )
                if not cap_ok:
                    cap_result = OutboundComplianceResult(
                        allowed=False,
                        reason="campaign_send_cap_reached",
                        details={"campaign_daily_count": campaign_daily_count},
                    )
                    self.compliance_service.apply_suppression(
                        campaign_contact, cap_result, datetime.now(UTC)
                    )
                    log.info(
                        "compliance_suppressed_campaign_contact",
                        campaign_id=str(campaign.id),
                        campaign_contact_id=str(campaign_contact.id),
                        contact_id=contact.id,
                        reason=cap_result.reason,
                        action_type=action_type,
                        channel=channel,
                    )
                    continue

            if not await self.number_pool.reserve_number_for_send(from_phone, db):
                log.warning("Selected follow-up number became rate limited")
                break

            try:
                message_text = self._render_template(
                    campaign.follow_up_message,
                    contact,
                    campaign.offer,
                )

                # Stable per-(campaign_contact, follow_up_index) key. The
                # current ``follow_ups_sent`` is the next follow-up's index
                # because it's incremented only after a successful send.
                followup_key = derive_outbound_key(
                    "campaign_sms_followup",
                    campaign_contact.id,
                    campaign_contact.follow_ups_sent,
                )

                text_service = self._get_text_provider(from_phone, text_providers)

                message = await text_service.send_message(
                    to_number=contact.phone_number,
                    from_number=_sender_address_for_phone(from_phone),
                    body=message_text,
                    db=db,
                    workspace_id=campaign.workspace_id,
                    agent_id=campaign.agent_id,
                    phone_number_id=from_phone.id,
                    idempotency_key=followup_key,
                )

                # Update phone number and stats
                from_phone.last_sent_at = datetime.now(UTC)
                await self.reputation_tracker.increment_sent(from_phone.id, db)

                campaign_contact.follow_ups_sent += 1
                campaign_contact.messages_sent += 1
                campaign_contact.last_sent_at = datetime.now(UTC)
                self.record_items_processed()

                if campaign_contact.follow_ups_sent < campaign.max_follow_ups:
                    campaign_contact.next_follow_up_at = datetime.now(UTC) + timedelta(
                        hours=campaign.follow_up_delay_hours
                    )
                else:
                    campaign_contact.next_follow_up_at = None
                    if campaign_contact.status != CampaignContactStatus.REPLIED:
                        campaign_contact.status = CampaignContactStatus.COMPLETED

                campaign.messages_sent += 1
                sent_count += 1

                log.info(
                    "Follow-up message sent",
                    contact_id=contact.id,
                    phone=contact.phone_number,
                    from_phone=from_phone.phone_number,
                    channel=channel,
                    follow_up_number=campaign_contact.follow_ups_sent,
                    message_id=str(message.id),
                    offer_id=str(campaign.offer_id) if campaign.offer_id else None,
                    has_offer=bool(campaign.offer_id),
                )

            except Exception as e:
                log.exception(
                    "Failed to send follow-up message",
                    contact_id=contact.id,
                    phone=contact.phone_number,
                    error=str(e),
                )
                campaign_contact.last_error = str(e)
                campaign.messages_failed += 1

        if sent_count > 0:
            log.info("Follow-up messages batch complete", sent=sent_count)

    def _render_template(
        self,
        template: str,
        contact: Contact,
        offer: Offer | None = None,
    ) -> str:
        """Render message template with contact and offer data.

        Safely interpolates placeholders with error handling to prevent
        template rendering failures from breaking campaign sending.

        Args:
            template: Message template with {placeholder} variables
            contact: Contact object with data to interpolate
            offer: Optional offer object with discount/details

        Returns:
            Rendered message with all placeholders replaced

        Raises:
            ValueError: If template rendering fails after error recovery
        """
        try:
            message = template
            full_name = " ".join(filter(None, [contact.first_name, contact.last_name])) or ""

            replacements: dict[str, str] = {
                "first_name": contact.first_name or "",
                "last_name": contact.last_name or "",
                "full_name": full_name,
                "company_name": contact.company_name or "",
                "email": contact.email or "",
            }

            # Add offer placeholders if offer exists
            if offer:
                try:
                    discount_text = ""
                    if offer.discount_type == "percentage":
                        discount_text = f"{offer.discount_value}% off"
                    elif offer.discount_type == "fixed":
                        discount_text = f"${offer.discount_value} off"
                    elif offer.discount_type == "free_service":
                        discount_text = "Free service"
                    else:
                        # Unknown discount type - log but continue
                        logger.warning(
                            "unknown_discount_type",
                            offer_id=str(offer.id) if hasattr(offer, "id") else "unknown",
                            discount_type=offer.discount_type,
                        )
                        discount_text = ""

                    replacements.update(
                        {
                            "offer_name": offer.name or "",
                            "offer_discount": discount_text,
                            "offer_description": offer.description or "",
                            "offer_terms": offer.terms or "",
                        }
                    )
                except Exception as e:
                    logger.error(
                        "offer_interpolation_error",
                        error=str(e),
                        offer_id=str(offer.id) if hasattr(offer, "id") else "unknown",
                    )
                    # Continue without offer details if error occurs

            # Replace placeholders safely (case-insensitive)
            for placeholder, value in replacements.items():
                try:
                    # Find placeholder pattern case-insensitively and replace with literal value
                    pattern = re.compile(rf"\{{{placeholder}\}}", re.IGNORECASE)
                    message = pattern.sub(value, message)
                except Exception as e:
                    logger.warning(
                        "placeholder_replacement_error",
                        placeholder=placeholder,
                        error=str(e),
                    )
                    # Continue with other placeholders if one fails

            return message

        except Exception as e:
            logger.error(
                "template_rendering_failed",
                error=str(e),
                template_length=len(template) if template else 0,
            )
            # Return original template if rendering completely fails
            return template


# Singleton registry
_registry = WorkerRegistry(CampaignWorker)
start_campaign_worker = _registry.start
stop_campaign_worker = _registry.stop
get_campaign_worker = _registry.get
