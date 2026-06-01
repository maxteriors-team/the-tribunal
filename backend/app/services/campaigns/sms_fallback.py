"""SMS fallback service for voice campaigns.

This service handles sending SMS messages when voice calls fail
(no answer, busy, voicemail, rejected).
"""

import contextlib
import re
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.campaign import Campaign, CampaignContact, CampaignContactStatus
from app.models.contact import Contact
from app.services.idempotency import derive_outbound_key
from app.services.telephony.telnyx import TelnyxSMSService

logger = structlog.get_logger()


async def send_sms_fallback(
    db: AsyncSession,
    campaign: Campaign,
    campaign_contact: CampaignContact,
    contact: Contact,
    call_outcome: str,
    telnyx_api_key: str,
) -> bool:
    """Send SMS fallback after call failure.

    Args:
        db: Database session
        campaign: The voice campaign
        campaign_contact: Campaign contact record
        contact: Contact record
        call_outcome: Why the call failed (no_answer, busy, voicemail, rejected)
        telnyx_api_key: Telnyx API key

    Returns:
        True if SMS was sent successfully
    """
    log = logger.bind(
        campaign_id=str(campaign.id),
        contact_id=contact.id,
        call_outcome=call_outcome,
    )

    if not campaign.sms_fallback_enabled:
        log.info("sms_fallback_disabled")
        return False

    if campaign_contact.sms_fallback_sent:
        log.info("sms_fallback_already_sent")
        return False

    # Determine message content
    message_text = None

    if campaign.sms_fallback_use_ai and campaign.sms_fallback_agent_id:
        # Generate AI message based on context
        try:
            from app.services.campaigns.ai_fallback import generate_sms_fallback_message

            message_text = await generate_sms_fallback_message(
                db=db,
                campaign=campaign,
                contact=contact,
                call_outcome=call_outcome,
            )
        except Exception as e:
            log.exception("ai_fallback_generation_failed", error=str(e))
            # Fall back to template if AI fails
            if campaign.sms_fallback_template:
                message_text = render_fallback_template(
                    campaign.sms_fallback_template,
                    contact,
                    call_outcome,
                )

    elif campaign.sms_fallback_template:
        # Use template
        message_text = render_fallback_template(
            campaign.sms_fallback_template,
            contact,
            call_outcome,
        )

    if not message_text:
        log.warning("no_fallback_message_configured")
        return False

    # Send SMS
    sms_service = TelnyxSMSService(telnyx_api_key)
    try:
        idempotency_key = derive_outbound_key(
            "voice_campaign_sms_fallback",
            campaign_contact.id,
            call_outcome,
        )
        message = await sms_service.send_message(
            to_number=contact.phone_number,
            from_number=campaign.from_phone_number,
            body=message_text,
            db=db,
            workspace_id=campaign.workspace_id,
            agent_id=campaign.sms_fallback_agent_id or campaign.agent_id,
            idempotency_key=idempotency_key,
        )

        # Update campaign contact
        campaign_contact.sms_fallback_sent = True
        campaign_contact.sms_fallback_sent_at = datetime.now(UTC)
        campaign_contact.sms_fallback_message_id = message.id
        campaign_contact.status = CampaignContactStatus.SMS_FALLBACK_SENT
        campaign_contact.conversation_id = message.conversation_id
        campaign_contact.messages_sent += 1

        # Update campaign stats
        campaign.sms_fallbacks_sent += 1
        campaign.messages_sent += 1

        await db.commit()

        log.info("sms_fallback_sent", message_id=str(message.id))
        return True

    except Exception as e:
        log.exception("sms_fallback_failed", error=str(e))
        campaign_contact.last_error = f"SMS fallback failed: {e}"
        await db.commit()
        return False
    finally:
        await sms_service.close()


def render_fallback_template(
    template: str,
    contact: Contact,
    call_outcome: str,
) -> str:
    """Render SMS fallback template with contact data.

    Args:
        template: Message template with {placeholder} variables
        contact: Contact object with data to interpolate
        call_outcome: Why the call failed

    Returns:
        Rendered message with all placeholders replaced
    """
    full_name = " ".join(filter(None, [contact.first_name, contact.last_name])) or ""

    # Map call outcomes to friendly text
    outcome_text_map = {
        "no_answer": "we tried calling but couldn't reach you",
        "busy": "your line was busy when we called",
        "voicemail": "we left a message but wanted to follow up",
        "rejected": "we tried calling earlier",
    }
    call_reason = outcome_text_map.get(call_outcome, "we tried reaching you by phone")

    replacements: dict[str, str] = {
        "first_name": contact.first_name or "",
        "last_name": contact.last_name or "",
        "full_name": full_name,
        "company_name": contact.company_name or "",
        "email": contact.email or "",
        "call_outcome": call_outcome,
        "call_reason": call_reason,
    }

    message = template
    for placeholder, value in replacements.items():
        with contextlib.suppress(Exception):
            # Find placeholder pattern case-insensitively and replace with literal value
            pattern = re.compile(rf"\{{{placeholder}\}}", re.IGNORECASE)
            message = pattern.sub(value, message)

    return message


async def trigger_sms_fallback_for_call(
    call_control_id: str,
    call_outcome: str,
    log: structlog.BoundLogger,
) -> bool:
    """Trigger SMS fallback for a failed campaign call.

    This function is called from the webhook handler when a call fails.

    Args:
        call_control_id: Telnyx call control ID
        call_outcome: Why the call failed (no_answer, busy, voicemail, rejected)
        log: Logger instance

    Returns:
        True if SMS fallback was triggered successfully
    """
    from app.db.session import AsyncSessionLocal
    from app.models.conversation import Message

    log.info("trigger_sms_fallback_started", call_control_id=call_control_id)

    async with AsyncSessionLocal() as db:
        # Find the message by call_control_id
        msg_result = await db.execute(
            select(Message).where(Message.provider_message_id == call_control_id)
        )
        message = msg_result.scalar_one_or_none()

        if not message:
            log.warning("message_not_found_for_fallback", call_control_id=call_control_id)
            return False

        log.info("found_message", message_id=str(message.id))

        # Find campaign contact linked to this call
        cc_result = await db.execute(
            select(CampaignContact)
            .options(
                selectinload(CampaignContact.campaign),
                selectinload(CampaignContact.contact),
            )
            .where(CampaignContact.call_message_id == message.id)
        )
        campaign_contact = cc_result.scalar_one_or_none()

        if not campaign_contact:
            log.info("not_a_campaign_call", message_id=str(message.id))
            return False

        log.info("found_campaign_contact", campaign_contact_id=str(campaign_contact.id))

        campaign = campaign_contact.campaign
        contact = campaign_contact.contact

        if not campaign or not contact:
            log.warning("missing_campaign_or_contact")
            return False

        if campaign.campaign_type != "voice_sms_fallback":
            log.info(
                "campaign_not_voice_sms_fallback",
                campaign_type=campaign.campaign_type,
            )
            return False

        # Stats are already updated by campaign_call_stats.update_campaign_call_stats()
        # before this function is called — no need to duplicate here.

        # Send SMS fallback
        if not settings.telnyx_api_key:
            log.warning("no_telnyx_api_key_for_fallback")
            return False

        # Refresh relationships after commit
        await db.refresh(campaign_contact)
        camp_result = await db.execute(
            select(Campaign).where(Campaign.id == campaign_contact.campaign_id)
        )
        refreshed_campaign = camp_result.scalar_one()
        contact_result = await db.execute(
            select(Contact).where(Contact.id == campaign_contact.contact_id)
        )
        refreshed_contact = contact_result.scalar_one()

        return await send_sms_fallback(
            db=db,
            campaign=refreshed_campaign,
            campaign_contact=campaign_contact,
            contact=refreshed_contact,
            call_outcome=call_outcome,
            telnyx_api_key=settings.telnyx_api_key,
        )
