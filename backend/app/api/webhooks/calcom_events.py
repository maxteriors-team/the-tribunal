"""Downstream event dispatch helpers for Cal.com webhooks.

Side-effect-heavy helpers extracted from ``calcom.py``:
- Lifecycle SMS rendering + sending
- From-number resolution for lifecycle SMS
- Workspace owner lookup for realtor email notifications
- Campaign resolution for new appointments
- Recent voice-message linking
"""

from __future__ import annotations

import re
import uuid
import zoneinfo
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.campaign import Campaign, CampaignContact
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.idempotency import derive_outbound_key
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.telnyx import TelnyxSMSService

logger = structlog.get_logger()

# Re-exported for handler convenience.
__all__ = [
    "DEFAULT_CONFIRMATION_BODY",
    "build_confirmation_body",
    "find_recent_voice_message",
    "get_workspace_owner",
    "resolve_campaign_id",
    "resolve_sms_from_number",
    "send_lifecycle_sms",
]


DEFAULT_CONFIRMATION_BODY = (
    "Hi {first_name}! Your appointment is confirmed for {appointment_date} at "
    "{appointment_time}. We'll send you a reminder beforehand. "
    "Reply here if you need to reschedule."
)


async def find_recent_voice_message(
    db: Any,
    contact_id: int,
    agent_id: Any,
    log: Any,
) -> Any:
    """Find a recent voice message for a contact+agent (within 10 minutes)."""
    try:
        cutoff = datetime.now(UTC) - timedelta(minutes=10)
        msg_query = (
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.contact_id == contact_id,
                Message.channel == "voice",
                Message.created_at >= cutoff,
            )
        )
        if agent_id:
            msg_query = msg_query.where(Message.agent_id == agent_id)
        msg_query = msg_query.order_by(Message.created_at.desc()).limit(1)
        msg_result = await db.execute(msg_query)
        recent_msg = msg_result.scalar_one_or_none()
        if recent_msg:
            msg_id: uuid.UUID = recent_msg.id
            log.info("linked_appointment_to_message", message_id=str(msg_id))
            return msg_id
    except Exception as e:
        log.warning("message_linking_failed", error=str(e))
    return None


async def get_workspace_owner(
    db: Any,
    workspace_id: uuid.UUID,
) -> tuple[str, str] | None:
    """Return ``(email, full_name)`` for the workspace owner or first admin.

    Falls back to the first member if no owner/admin exists.
    Returns ``None`` when the workspace has no members.
    """
    for role in ("owner", "admin", "member"):
        result = await db.execute(
            select(User.email, User.full_name)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == role,
            )
            .limit(1)
        )
        row = result.first()
        if row:
            email: str = row[0]
            full_name: str = row[1] or email.split("@")[0]
            return email, full_name
    return None


async def resolve_campaign_id(db: Any, contact_id: int, log: Any) -> Any:
    """Find the most recent active campaign for a contact."""
    try:
        cc_result = await db.execute(
            select(CampaignContact.campaign_id)
            .join(Campaign, CampaignContact.campaign_id == Campaign.id)
            .where(
                CampaignContact.contact_id == contact_id,
                Campaign.status.in_(["running", "paused"]),
            )
            .order_by(CampaignContact.created_at.desc())
            .limit(1)
        )
        cc_row = cc_result.first()
        if cc_row:
            log.info("resolved_campaign_for_appointment", campaign_id=str(cc_row[0]))
            return cc_row[0]
    except Exception as e:
        log.warning("campaign_resolution_failed", error=str(e))
    return None


async def resolve_sms_from_number(
    db: AsyncSession,
    contact_id: int,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID | None,
) -> str | None:
    """Resolve the best from-number for a lifecycle SMS.

    Strategy 1: Reuse an existing conversation with this contact.
    Strategy 2: Fall back to the agent's assigned SMS-enabled phone number.
    Strategy 3: Fall back to any active SMS-enabled workspace phone number.
    """
    # Strategy 1 — existing conversation
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

    # Strategy 2 — agent's assigned phone number
    if agent_id is not None:
        result = await db.execute(
            select(PhoneNumber.phone_number)
            .where(
                and_(
                    PhoneNumber.assigned_agent_id == agent_id,
                    PhoneNumber.is_active.is_(True),
                    PhoneNumber.sms_enabled.is_(True),
                )
            )
            .limit(1)
        )
        phone = result.scalar_one_or_none()
        if phone:
            return str(phone)

    # Strategy 3 — any active SMS-enabled workspace phone number
    result = await db.execute(
        select(PhoneNumber.phone_number)
        .where(
            and_(
                PhoneNumber.workspace_id == workspace_id,
                PhoneNumber.is_active.is_(True),
                PhoneNumber.sms_enabled.is_(True),
            )
        )
        .order_by(PhoneNumber.created_at)
        .limit(1)
    )
    phone = result.scalar_one_or_none()
    if phone:
        return str(phone)

    return None


def build_confirmation_body(
    contact: Contact,
    appointment: Appointment,
    workspace: Workspace | None,
    agent: Agent | None,
) -> str:
    """Build the confirmation SMS body.

    Uses ``agent.reminder_template`` when set (note: this is the reminder
    template repurposed for confirmation; a dedicated confirmation_template
    field may be added in a future iteration). Falls back to
    :data:`DEFAULT_CONFIRMATION_BODY`.

    Times are formatted in the workspace timezone (falls back to UTC).
    """
    tz_name = ((workspace.settings if workspace else None) or {}).get("timezone", "UTC")
    try:
        tz = zoneinfo.ZoneInfo(str(tz_name))
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        tz = zoneinfo.ZoneInfo("UTC")

    local_dt = appointment.scheduled_at.astimezone(tz)
    date_str = local_dt.strftime("%A, %B %-d")  # e.g. "Monday, March 24"
    time_str = local_dt.strftime("%-I:%M %p")  # e.g. "3:00 PM"

    first_name = contact.first_name or "there"
    template = agent.reminder_template if agent is not None else None

    if not template:
        return DEFAULT_CONFIRMATION_BODY.format(
            first_name=first_name,
            appointment_date=date_str,
            appointment_time=time_str,
        )

    # Build reschedule link if agent has a Cal.com event type configured
    reschedule_link = ""
    if agent is not None and agent.calcom_event_type_id and settings.calcom_api_key:
        try:
            from app.services.calendar.calcom import CalComService

            calcom = CalComService(settings.calcom_api_key)
            contact_name = (
                " ".join(filter(None, [contact.first_name, contact.last_name])) or first_name
            )
            reschedule_link = calcom.generate_booking_url(
                event_type_id=agent.calcom_event_type_id,
                contact_email=contact.email or "",
                contact_name=contact_name,
                contact_phone=contact.phone_number,
            )
        except Exception:
            logger.warning(
                "confirmation_sms_reschedule_link_failed",
                appointment_id=appointment.id,
            )

    replacements: dict[str, str] = {
        "first_name": contact.first_name or "",
        "last_name": contact.last_name or "",
        "appointment_date": date_str,
        "appointment_time": time_str,
        "appointment_datetime": f"{date_str} at {time_str}",
        "reschedule_link": reschedule_link,
    }

    message = template
    for placeholder, value in replacements.items():
        try:
            pattern = re.compile(rf"\{{{placeholder}\}}", re.IGNORECASE)
            message = pattern.sub(value, message)
        except Exception:
            pass  # Non-fatal; leave placeholder as-is

    return message


async def send_lifecycle_sms(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact: Contact,
    agent: Agent | None,
    body_text: str,
    idempotency_scope: str | None = None,
    idempotency_parts: tuple[object, ...] = (),
) -> None:
    """Send a lifecycle SMS (confirmation, cancellation, etc.) to a contact.

    This is a shared helper used by all lifecycle SMS touch-points. It:
    - Checks contact has a phone number
    - Resolves the from-number (existing convo > agent number > workspace number)
    - Checks TCPA opt-out compliance before sending
    - Sends via :class:`TelnyxSMSService`
    - Logs success/failure at appropriate levels
    - Is entirely wrapped in try/except — never raises, caller always gets ``None``

    Args:
        db: Active database session (must be open; this helper may commit).
        workspace_id: Workspace UUID.
        contact: Contact ORM object (needs ``.phone_number``, ``.id``).
        agent: Optional Agent ORM object (used for from-number resolution).
        body_text: Pre-rendered SMS body text.
        idempotency_scope: Optional outbound key scope for webhook retries.
        idempotency_parts: Stable domain identifiers for the outbound key.
    """
    try:
        telnyx_key = settings.telnyx_api_key
        if not telnyx_key:
            logger.warning("lifecycle_sms_no_telnyx_key", contact_id=contact.id)
            return

        contact_phone = contact.phone_number
        if not contact_phone:
            logger.debug("lifecycle_sms_skipped_no_phone", contact_id=contact.id)
            return

        agent_id = agent.id if agent is not None else None

        # TCPA compliance — respect opt-outs
        opt_out_manager = OptOutManager()
        is_opted_out = await opt_out_manager.check_opt_out(workspace_id, contact_phone, db)
        if is_opted_out:
            logger.info(
                "lifecycle_sms_skipped_opted_out",
                contact_id=contact.id,
                phone=contact_phone,
            )
            return

        from_number = await resolve_sms_from_number(db, contact.id, workspace_id, agent_id)
        if not from_number:
            logger.warning(
                "lifecycle_sms_no_from_number",
                contact_id=contact.id,
                workspace_id=str(workspace_id),
            )
            return

        idempotency_key = None
        if idempotency_scope is not None:
            idempotency_key = derive_outbound_key(idempotency_scope, *idempotency_parts)

        sms_service = TelnyxSMSService(telnyx_key)
        try:
            message = await sms_service.send_message(
                to_number=contact_phone,
                from_number=from_number,
                body=body_text,
                db=db,
                workspace_id=workspace_id,
                agent_id=agent_id,
                idempotency_key=idempotency_key,
            )
            logger.info(
                "lifecycle_sms_sent",
                contact_id=contact.id,
                message_id=str(message.id),
            )
        finally:
            await sms_service.close()

    except Exception as e:
        logger.exception(
            "lifecycle_sms_failed",
            contact_id=contact.id,
            error=str(e),
        )
