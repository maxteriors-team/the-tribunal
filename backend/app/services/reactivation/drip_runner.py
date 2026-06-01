"""Core drip sequence runner — advances enrollments through steps.

Called by the drip_campaign_worker on each poll cycle. For each enrollment
that is due (status=active, next_step_at <= now):
1. Check disqualification gates (opt-out, contact deleted, etc.)
2. Render the message template
3. Send SMS via Telnyx
4. Advance to the next step or mark as completed
"""

import re
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.drip_campaign import (
    DripCampaign,
    DripCampaignStatus,
    DripEnrollment,
    DripEnrollmentStatus,
)
from app.services.idempotency import derive_outbound_key
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.telnyx import TelnyxSMSService

logger = structlog.get_logger()

MAX_ENROLLMENTS_PER_TICK = 30


async def process_active_drip_campaigns(db: AsyncSession) -> None:
    """Process all active drip campaigns — called by the worker."""
    result = await db.execute(
        select(DripCampaign).where(
            DripCampaign.status == DripCampaignStatus.ACTIVE,
        )
    )
    campaigns = result.scalars().all()

    for campaign in campaigns:
        try:
            await _process_campaign(campaign, db)
        except Exception:
            logger.exception(
                "drip_campaign_processing_error",
                campaign_id=str(campaign.id),
            )


async def _process_campaign(campaign: DripCampaign, db: AsyncSession) -> None:
    """Process a single drip campaign: send due messages and check completion."""
    log = logger.bind(
        campaign_id=str(campaign.id),
        campaign_name=campaign.name,
    )

    if not _is_within_sending_hours(campaign):
        log.debug("drip_outside_sending_hours")
        return

    if not settings.telnyx_api_key:
        log.warning("no_telnyx_api_key")
        return

    now = datetime.now(UTC)

    # Get enrollments that are due
    result = await db.execute(
        select(DripEnrollment)
        .options(selectinload(DripEnrollment.contact))
        .where(
            and_(
                DripEnrollment.drip_campaign_id == campaign.id,
                DripEnrollment.status == DripEnrollmentStatus.ACTIVE,
                DripEnrollment.next_step_at.is_not(None),
                DripEnrollment.next_step_at <= now,
            )
        )
        .order_by(DripEnrollment.next_step_at)
        .limit(MAX_ENROLLMENTS_PER_TICK)
        .with_for_update(skip_locked=True)
    )
    enrollments = result.scalars().all()

    if not enrollments:
        # Check if all enrollments are done
        await _check_campaign_completion(campaign, db, log)
        return

    log.info("processing_drip_enrollments", count=len(enrollments))

    opt_out_manager = OptOutManager()
    sms_service = TelnyxSMSService(settings.telnyx_api_key)

    try:
        for enrollment in enrollments:
            try:
                await _process_enrollment(
                    enrollment, campaign, sms_service, opt_out_manager, db, log
                )
            except Exception:
                log.exception(
                    "drip_enrollment_error",
                    contact_id=enrollment.contact_id,
                    step=enrollment.current_step,
                )
        await db.commit()
    finally:
        await sms_service.close()


async def _process_enrollment(
    enrollment: DripEnrollment,
    campaign: DripCampaign,
    sms_service: TelnyxSMSService,
    opt_out_manager: OptOutManager,
    db: AsyncSession,
    log: Any,
) -> None:
    """Process a single enrollment: send the current step's message."""
    contact = enrollment.contact
    if not contact or not contact.phone_number:
        enrollment.status = DripEnrollmentStatus.CANCELLED
        enrollment.cancel_reason = "missing_phone"
        enrollment.completed_at = datetime.now(UTC)
        campaign.total_cancelled += 1
        return

    # Check opt-out
    is_opted_out = await opt_out_manager.check_opt_out(
        campaign.workspace_id, contact.phone_number, db
    )
    if is_opted_out:
        enrollment.status = DripEnrollmentStatus.CANCELLED
        enrollment.cancel_reason = "opted_out"
        enrollment.completed_at = datetime.now(UTC)
        campaign.total_cancelled += 1
        log.info("drip_skipped_opted_out", contact_id=contact.id)
        return

    # Get the current step config
    steps = campaign.sequence_steps or []
    current_step_config = None
    for s in steps:
        if s.get("step") == enrollment.current_step:
            current_step_config = s
            break

    if current_step_config is None:
        # Past all steps — mark complete
        enrollment.status = DripEnrollmentStatus.COMPLETED
        enrollment.completed_at = datetime.now(UTC)
        enrollment.next_step_at = None
        campaign.total_completed += 1
        return

    # Render message
    message_text = _render_template(current_step_config["message"], contact)

    # Resolve from number (prefer conversation continuity)
    from_number = await _resolve_from_number(
        db, contact.id, campaign.workspace_id, campaign.from_phone_number
    )

    # Stable per-(enrollment, step) key so a worker crash between the
    # Message row insert and the Telnyx POST is recoverable on the next
    # poll cycle without re-sending the same drip step.
    idempotency_key = derive_outbound_key("drip_step", enrollment.id, enrollment.current_step)

    # Send SMS
    message = await sms_service.send_message(
        to_number=contact.phone_number,
        from_number=from_number,
        body=message_text,
        db=db,
        workspace_id=campaign.workspace_id,
        agent_id=campaign.agent_id,
        idempotency_key=idempotency_key,
    )

    log.info(
        "drip_message_sent",
        contact_id=contact.id,
        step=enrollment.current_step,
        step_type=current_step_config.get("type"),
        message_id=str(message.id),
    )

    # Assign agent to conversation so AI takes over on reply
    if campaign.agent_id and message.conversation_id:
        await db.execute(
            update(Conversation)
            .where(Conversation.id == message.conversation_id)
            .values(
                assigned_agent_id=campaign.agent_id,
                ai_enabled=True,
            )
        )

    # Update enrollment
    enrollment.messages_sent += 1
    enrollment.last_sent_at = datetime.now(UTC)

    # Advance to next step
    next_step_num = enrollment.current_step + 1
    next_step_config = None
    for s in steps:
        if s.get("step") == next_step_num:
            next_step_config = s
            break

    if next_step_config is not None:
        enrollment.current_step = next_step_num
        delay = next_step_config.get("delay_days", 1)
        enrollment.next_step_at = datetime.now(UTC) + timedelta(days=delay)
    else:
        # All steps sent — mark completed
        enrollment.status = DripEnrollmentStatus.COMPLETED
        enrollment.completed_at = datetime.now(UTC)
        enrollment.next_step_at = None
        campaign.total_completed += 1

    # Update campaign stats
    campaign.total_messages_sent += 1


async def enroll_contacts(
    campaign: DripCampaign,
    contact_ids: list[int],
    db: AsyncSession,
) -> int:
    """Enroll contacts in a drip campaign. Returns count enrolled."""
    steps = campaign.sequence_steps or []
    if not steps:
        return 0

    first_step = steps[0]
    delay_days = first_step.get("delay_days", 0)
    now = datetime.now(UTC)
    next_step_at = now + timedelta(days=delay_days) if delay_days > 0 else now

    # Get already-enrolled contact IDs to skip duplicates
    existing_result = await db.execute(
        select(DripEnrollment.contact_id).where(
            DripEnrollment.drip_campaign_id == campaign.id,
            DripEnrollment.contact_id.in_(contact_ids),
        )
    )
    existing_ids = set(existing_result.scalars().all())

    enrolled = 0
    for cid in contact_ids:
        if cid in existing_ids:
            continue
        enrollment = DripEnrollment(
            drip_campaign_id=campaign.id,
            contact_id=cid,
            status=DripEnrollmentStatus.ACTIVE,
            current_step=0,
            next_step_at=next_step_at,
        )
        db.add(enrollment)
        enrolled += 1

    campaign.total_enrolled += enrolled
    return enrolled


async def handle_inbound_reply(
    contact_id: int,
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Called when an inbound SMS arrives — pauses any active drip enrollment.

    The AI text agent handles the actual response. This just ensures we stop
    the drip cadence while the conversation is live.
    """
    result = await db.execute(
        select(DripEnrollment)
        .join(DripCampaign)
        .where(
            and_(
                DripCampaign.workspace_id == workspace_id,
                DripEnrollment.contact_id == contact_id,
                DripEnrollment.status == DripEnrollmentStatus.ACTIVE,
            )
        )
    )
    enrollments = result.scalars().all()

    for enrollment in enrollments:
        enrollment.status = DripEnrollmentStatus.RESPONDED
        enrollment.last_reply_at = datetime.now(UTC)
        enrollment.messages_received += 1
        enrollment.next_step_at = None

        # Update campaign stats
        campaign_result = await db.execute(
            select(DripCampaign).where(DripCampaign.id == enrollment.drip_campaign_id)
        )
        campaign = campaign_result.scalar_one_or_none()
        if campaign:
            campaign.total_responded += 1

    if enrollments:
        logger.info(
            "drip_paused_on_reply",
            contact_id=contact_id,
            workspace_id=str(workspace_id),
            enrollment_count=len(enrollments),
        )


async def _check_campaign_completion(
    campaign: DripCampaign,
    db: AsyncSession,
    log: Any,
) -> None:
    """Check if all enrollments are done and mark campaign as completed."""
    active_count_result = await db.execute(
        select(func.count(DripEnrollment.id)).where(
            DripEnrollment.drip_campaign_id == campaign.id,
            DripEnrollment.status == DripEnrollmentStatus.ACTIVE,
        )
    )
    active_count = active_count_result.scalar() or 0

    if active_count == 0 and campaign.total_enrolled > 0:
        campaign.status = DripCampaignStatus.COMPLETED
        campaign.completed_at = datetime.now(UTC)
        await db.commit()
        log.info("drip_campaign_completed")


def _render_template(template: str, contact: Contact) -> str:
    """Render a drip message template with contact placeholders."""
    first_name = contact.first_name or "there"
    full_name = " ".join(filter(None, [contact.first_name, contact.last_name])) or ""

    replacements: dict[str, str] = {
        "first_name": first_name,
        "last_name": contact.last_name or "",
        "full_name": full_name,
    }

    message = template
    for placeholder, value in replacements.items():
        pattern = re.compile(rf"\{{{placeholder}\}}", re.IGNORECASE)
        message = pattern.sub(value, message)
    return message


async def _resolve_from_number(
    db: AsyncSession,
    contact_id: int,
    workspace_id: uuid.UUID,
    default_number: str,
) -> str:
    """Resolve from-number, preferring conversation continuity."""
    # Try existing conversation first
    result = await db.execute(
        select(Conversation.workspace_phone)
        .where(
            and_(
                Conversation.contact_id == contact_id,
                Conversation.workspace_id == workspace_id,
            )
        )
        .order_by(Conversation.last_message_at.desc().nulls_last())
        .limit(1)
    )
    phone = result.scalar_one_or_none()
    if phone:
        return str(phone)

    return default_number


def _is_within_sending_hours(campaign: DripCampaign) -> bool:
    """Check if current time is within campaign sending hours."""
    if campaign.sending_hours_start is None or campaign.sending_hours_end is None:
        return True

    tz = ZoneInfo(campaign.timezone or "UTC")
    now = datetime.now(tz)

    if campaign.sending_days and now.weekday() not in campaign.sending_days:
        return False

    start_val = campaign.sending_hours_start
    end_val = campaign.sending_hours_end
    start_time: time = start_val.time() if isinstance(start_val, datetime) else start_val
    end_time: time = end_val.time() if isinstance(end_val, datetime) else end_val

    return start_time <= now.time() <= end_time
