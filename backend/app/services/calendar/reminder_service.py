"""Shared reminder-sending logic for calendar appointments and field jobs.

Both manual calendar actions and future workers use these stock, opt-out-checked
SMS paths instead of accepting caller-supplied message content.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageStatus
from app.models.field_service import Job
from app.models.phone_number import PhoneNumber
from app.models.workspace import Workspace
from app.services.email import send_appointment_reminder_email
from app.services.idempotency import derive_outbound_key, resolve_message_idempotency
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.telnyx import TelnyxSMSService
from app.utils.timezones import resolve_workspace_timezone, workspace_timezone_name

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


def _schedule_revision(value: datetime) -> str:
    """Normalize a scheduled instant for stable, reschedule-aware idempotency."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


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
    Times are formatted in the workspace timezone — the zone the appointment was
    booked in, so a reminder cannot quote a different hour than the confirmation.
    """
    local_dt = appointment.scheduled_at.astimezone(resolve_workspace_timezone(workspace))
    date_str = local_dt.strftime("%A, %B %-d")
    time_str = "any time" if appointment.anytime else local_dt.strftime("%-I:%M %p")
    datetime_str = f"{date_str} at {time_str}"

    first_name = contact.first_name or "there"

    if not template:
        return (
            f"Hi {first_name}, just a reminder about your upcoming appointment "
            f"at {time_str}. Check your email for the video call link. "
            f"Reply here if you need to reschedule."
        )

    # Scheduling is self-contained: there is no external reschedule URL, so
    # ``{reschedule_link}`` renders empty and templates fall back to the
    # "reply to reschedule" copy.
    reschedule_link = ""

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


def render_job_reminder_body(job: Job, contact: Contact, workspace: Workspace) -> str:
    """Render the stock customer reminder used by manual and automated job sends."""
    if job.scheduled_start is None:
        raise ValueError("Cannot render a reminder for an unscheduled job")

    scheduled_start = job.scheduled_start
    if scheduled_start.tzinfo is None:
        scheduled_start = scheduled_start.replace(tzinfo=UTC)
    local_dt = scheduled_start.astimezone(resolve_workspace_timezone(workspace))
    date_str = local_dt.strftime("%A, %B %-d")
    time_str = local_dt.strftime("%-I:%M %p")
    first_name = contact.first_name or "there"
    business_name = workspace.name or "our team"
    return (
        f"Hi {first_name}, this is a reminder of your scheduled visit with "
        f"{business_name} on {date_str} at {time_str}. "
        "Reply here if you need to make changes."
    )


# ---------------------------------------------------------------------------
# Email reminder
# ---------------------------------------------------------------------------


async def send_appointment_reminder_email_for(
    appointment: Appointment,
    workspace: Workspace,
    contact: Contact,
    agent: Agent | None,
) -> bool:
    """Email ``contact`` a reminder using the same body the SMS reminder renders.

    Sharing ``render_reminder_body`` is the point: two independent renderers is
    how one channel ends up quoting a different hour than the other. Returns
    False when there is no address or the provider rejected the send.
    """
    if not contact.email:
        return False

    body = render_reminder_body(
        template=agent.reminder_template if agent is not None else None,
        contact=contact,
        appointment=appointment,
        workspace=workspace,
        agent=agent,
    )
    return await send_appointment_reminder_email(
        to_email=contact.email,
        contact_name=contact.full_name or "there",
        business_name=workspace.name or "",
        body_text=body,
        appointment_time=appointment.scheduled_at,
        timezone=workspace_timezone_name(workspace),
        idempotency_key=derive_outbound_key("manual_appointment_reminder_email", appointment.id),
        anytime=appointment.anytime,
    )


# ---------------------------------------------------------------------------
# Core send functions
# ---------------------------------------------------------------------------


async def _existing_reminder_result(
    db: AsyncSession,
    idempotency_key: uuid.UUID,
    contact_phone: str,
    log: Any,
) -> dict[str, Any] | None:
    """Return the truthful result of replaying an already-applied reminder."""
    idempotency = await resolve_message_idempotency(db, idempotency_key)
    if not idempotency.should_skip or idempotency.existing_message is None:
        return None

    existing = idempotency.existing_message
    if existing.status in {MessageStatus.FAILED, MessageStatus.FAILED.value}:
        log.warning("previous_reminder_failed", message_id=str(existing.id))
        return {"success": False, "message": "Previous reminder attempt failed", "sent_to": None}

    log.info("reminder_already_sent", message_id=str(existing.id))
    return {
        "success": True,
        "message": "Reminder already sent for this schedule",
        "sent_to": mask_phone(contact_phone),
        "already_sent": True,
    }


def _delivery_result(message: Message, contact_phone: str, log: Any) -> dict[str, Any]:
    """Translate the persisted provider result without claiming a failed send succeeded."""
    if message.status in {MessageStatus.FAILED, MessageStatus.FAILED.value}:
        log.warning("reminder_provider_failed", message_id=str(message.id))
        return {"success": False, "message": "Reminder could not be sent", "sent_to": None}

    log.info("reminder_sent", message_id=str(message.id))
    return {
        "success": True,
        "message": "Reminder sent",
        "sent_to": mask_phone(contact_phone),
        "already_sent": False,
    }


async def _send_sms_reminder(
    *,
    db: AsyncSession,
    workspace: Workspace,
    contact: Contact,
    agent_id: uuid.UUID | None,
    body: str,
    idempotency_key: uuid.UUID,
    sender_user_id: int | None,
    sender_display_name: str | None,
    log: Any,
) -> dict[str, Any]:
    """Apply the shared SMS safety gates and send one stock reminder."""
    telnyx_key = settings.telnyx_api_key
    if not telnyx_key:
        log.warning("no_telnyx_api_key")
        return {"success": False, "message": "Telnyx API key not configured", "sent_to": None}

    contact_phone = contact.phone_number
    if not contact_phone:
        log.warning("contact_has_no_phone", contact_id=contact.id)
        return {"success": False, "message": "Contact has no phone number", "sent_to": None}

    if contact.sms_consent_status == "opted_out" or await _opt_out_manager.check_opt_out(
        workspace.id, contact_phone, db
    ):
        log.info("contact_opted_out", contact_id=contact.id)
        return {"success": False, "message": "Contact has opted out of SMS", "sent_to": None}

    existing_result = await _existing_reminder_result(db, idempotency_key, contact_phone, log)
    if existing_result is not None:
        return existing_result

    from_number = await resolve_from_number(db, contact.id, workspace.id, agent_id)
    if not from_number:
        log.warning("could_not_resolve_from_number")
        return {
            "success": False,
            "message": "Could not find a sending phone number for this workspace",
            "sent_to": None,
        }

    sms_service = TelnyxSMSService(telnyx_key)
    try:
        message = await sms_service.send_message(
            to_number=contact_phone,
            from_number=from_number,
            body=body,
            db=db,
            workspace_id=workspace.id,
            agent_id=agent_id,
            idempotency_key=idempotency_key,
            sender_user_id=sender_user_id,
            sender_display_name=sender_display_name,
        )
    except Exception as exc:
        log.exception("failed_to_send_reminder", error=str(exc))
        raise
    finally:
        await sms_service.close()

    return _delivery_result(message, contact_phone, log)


async def send_appointment_reminder(
    db: AsyncSession,
    appointment: Appointment,
    workspace: Workspace,
    contact: Contact,
    agent: Agent | None,
    *,
    sender_user_id: int | None = None,
    sender_display_name: str | None = None,
) -> dict[str, Any]:
    """Send a manual SMS reminder for an appointment."""
    log = logger.bind(appointment_id=appointment.id, trigger="manual")
    body = render_reminder_body(
        template=agent.reminder_template if agent is not None else None,
        contact=contact,
        appointment=appointment,
        workspace=workspace,
        agent=agent,
    )
    result = await _send_sms_reminder(
        db=db,
        workspace=workspace,
        contact=contact,
        agent_id=agent.id if agent is not None else None,
        body=body,
        idempotency_key=derive_outbound_key(
            "manual_appointment_reminder",
            appointment.id,
            _schedule_revision(appointment.scheduled_at),
            appointment.anytime,
        ),
        sender_user_id=sender_user_id,
        sender_display_name=sender_display_name,
        log=log,
    )
    if not result["success"] or result.get("already_sent"):
        return result

    # Update manual-send state without touching automatic offset tracking.
    now = datetime.now(UTC)
    await db.execute(
        text("UPDATE appointments SET reminder_sent_at = :now WHERE id = :appt_id"),
        {"now": now, "appt_id": appointment.id},
    )
    appointment.reminder_sent_at = now
    await db.commit()
    return result


async def send_job_reminder(
    db: AsyncSession,
    job: Job,
    workspace: Workspace,
    contact: Contact,
    *,
    action_type: str = "manual_job_reminder",
    offset_minutes: int | None = None,
    sender_user_id: int | None = None,
    sender_display_name: str | None = None,
) -> dict[str, Any]:
    """Send a stock job reminder; workers can reuse this with a distinct action key."""
    if job.scheduled_start is None:
        return {"success": False, "message": "Job is not scheduled", "sent_to": None}

    return await _send_sms_reminder(
        db=db,
        workspace=workspace,
        contact=contact,
        agent_id=None,
        body=render_job_reminder_body(job, contact, workspace),
        idempotency_key=derive_outbound_key(
            action_type,
            job.id,
            _schedule_revision(job.scheduled_start),
            offset_minutes,
        ),
        sender_user_id=sender_user_id,
        sender_display_name=sender_display_name,
        log=logger.bind(job_id=str(job.id), trigger=action_type, offset_minutes=offset_minutes),
    )
