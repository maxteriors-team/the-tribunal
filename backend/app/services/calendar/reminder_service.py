"""Shared reminder-sending logic for appointments.

Extracted from ReminderWorker so that both the background worker and the
manual "send reminder" API endpoint can call the same SMS dispatch path
without duplicating code.
"""

import re
import uuid
import zoneinfo
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.phone_number import PhoneNumber
from app.models.workspace import Workspace
from app.services.idempotency import derive_outbound_key
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.telnyx import TelnyxSMSService

logger = structlog.get_logger()

_opt_out_manager = OptOutManager()


# ---------------------------------------------------------------------------
# Phone masking helper
# ---------------------------------------------------------------------------


def mask_phone(phone: str) -> str:
    """Return a masked phone string, e.g. '***-***-1234' (last 4 digits shown)."""
    digits = re.sub(r"\D", "", phone)
    last4 = digits[-4:] if len(digits) >= 4 else digits
    return f"***-***-{last4}"


# ---------------------------------------------------------------------------
# From-number resolution (3-strategy, same as ReminderWorker)
# ---------------------------------------------------------------------------


async def resolve_from_number(
    db: AsyncSession,
    contact_id: int,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID | None,
) -> str | None:
    """Resolve the best from-number for a reminder SMS.

    Strategy 1: Existing conversation workspace_phone (maintains thread).
    Strategy 2: Agent's assigned SMS-enabled phone (if agent provided).
    Strategy 3: Any active SMS-enabled workspace phone (agentless fallback).
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


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def render_reminder_body(
    template: str | None,
    contact: Contact,
    appointment: Appointment,
    workspace: Workspace,
    agent: Agent | None,
) -> str:
    """Build the SMS body for a reminder.

    If *template* is provided, renders it with standard placeholders:
      {first_name}, {last_name}, {appointment_date}, {appointment_time},
      {appointment_datetime}, {reschedule_link}

    Falls back to a hardcoded default when no template is set.
    Times are formatted in the workspace timezone (falls back to UTC).
    """
    tz_name = (workspace.settings or {}).get("timezone", "UTC")
    try:
        tz = zoneinfo.ZoneInfo(str(tz_name))
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        tz = zoneinfo.ZoneInfo("UTC")

    local_dt = appointment.scheduled_at.astimezone(tz)
    date_str = local_dt.strftime("%A, %B %-d")
    time_str = local_dt.strftime("%-I:%M %p")
    datetime_str = f"{date_str} at {time_str}"

    first_name = contact.first_name or "there"

    if not template:
        return (
            f"Hi {first_name}, just a reminder about your upcoming appointment "
            f"at {time_str}. Check your email for the video call link. "
            f"Reply here if you need to reschedule."
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
                "Could not generate reschedule link for reminder template",
                appointment_id=appointment.id,
            )

    replacements: dict[str, str] = {
        "first_name": contact.first_name or "",
        "last_name": contact.last_name or "",
        "appointment_date": date_str,
        "appointment_time": time_str,
        "appointment_datetime": datetime_str,
        "reschedule_link": reschedule_link,
    }

    message = template
    for placeholder, value in replacements.items():
        try:
            pattern = re.compile(rf"\{{{placeholder}\}}", re.IGNORECASE)
            message = pattern.sub(value, message)
        except Exception:
            logger.warning(
                "Placeholder replacement failed in reminder template",
                placeholder=placeholder,
                appointment_id=appointment.id,
            )

    return message


# ---------------------------------------------------------------------------
# Core send function
# ---------------------------------------------------------------------------


async def send_appointment_reminder(
    db: AsyncSession,
    appointment: Appointment,
    workspace: Workspace,
    contact: Contact,
    agent: Agent | None,
) -> dict[str, Any]:
    """Send a manual SMS reminder for an appointment.

    Returns a dict with:
      - ``success``: bool
      - ``message``: human-readable description
      - ``sent_to``: masked phone string on success, None on failure
    """
    log = logger.bind(appointment_id=appointment.id, trigger="manual")

    telnyx_key = settings.telnyx_api_key
    if not telnyx_key:
        log.warning("no_telnyx_api_key")
        return {"success": False, "message": "Telnyx API key not configured", "sent_to": None}

    contact_phone = contact.phone_number
    if not contact_phone:
        log.warning("contact_has_no_phone", contact_id=contact.id)
        return {"success": False, "message": "Contact has no phone number", "sent_to": None}

    # TCPA compliance — skip opted-out contacts
    is_opted_out = await _opt_out_manager.check_opt_out(workspace.id, contact_phone, db)
    if is_opted_out:
        log.info("contact_opted_out", contact_id=contact.id)
        return {"success": False, "message": "Contact has opted out of SMS", "sent_to": None}

    agent_id = agent.id if agent is not None else None

    from_number = await resolve_from_number(db, contact.id, workspace.id, agent_id)
    if not from_number:
        log.warning("could_not_resolve_from_number")
        return {
            "success": False,
            "message": "Could not find a sending phone number for this workspace",
            "sent_to": None,
        }

    body = render_reminder_body(
        template=agent.reminder_template if agent is not None else None,
        contact=contact,
        appointment=appointment,
        workspace=workspace,
        agent=agent,
    )

    sms_service = TelnyxSMSService(telnyx_key)
    try:
        idempotency_key = derive_outbound_key("manual_appointment_reminder", appointment.id)
        message = await sms_service.send_message(
            to_number=contact_phone,
            from_number=from_number,
            body=body,
            db=db,
            workspace_id=workspace.id,
            agent_id=agent_id,
            idempotency_key=idempotency_key,
        )
        log.info("manual_reminder_sent", message_id=str(message.id))

        # Update reminder_sent_at without touching reminders_sent (offset tracking)
        now = datetime.now(UTC)
        await db.execute(
            text("UPDATE appointments SET reminder_sent_at = :now WHERE id = :appt_id"),
            {"now": now, "appt_id": appointment.id},
        )
        appointment.reminder_sent_at = now
        await db.commit()

        return {
            "success": True,
            "message": "Reminder sent",
            "sent_to": mask_phone(contact_phone),
        }

    except Exception as exc:
        log.exception("failed_to_send_manual_reminder", error=str(exc))
        raise
    finally:
        await sms_service.close()
