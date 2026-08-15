"""The single place an AI-booked appointment becomes real.

Three paths book appointments — the voice tool executor, the text tool executor,
and the HITL approval handler — and each one used to hand-roll its own "write the
row" step. That duplication is exactly how the approval path shipped without
writing a row at all: the booking reported success and landed on no calendar.

Everything that must happen when a booking succeeds lives here:

1. **Rep assignment** — resolve the bookable staff member via the agent's routing
   strategy so an appointment has an owner instead of sitting unassigned.
2. **The appointment row** — the CRM table is the source of truth for scheduling.
3. **Customer confirmation** — SMS where no live channel reply exists, plus an
   emailed ``.ics`` invitation so the meeting reaches the address collected at booking.
4. **Calendar invite to the rep** — an ``.ics`` attachment so the appointment
   shows up in the calendar they actually watch.

Notifications run *after* commit and are fire-and-forget: a texting or email
outage must never roll back a confirmed booking, and we must never text a
customer about an appointment whose transaction was rolled back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.automation import Automation
from app.models.automation_execution import AutomationExecution
from app.models.bookable_staff import BookableStaff
from app.models.contact import Contact
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.appointments.lifecycle_sms import build_confirmation_body, send_lifecycle_sms
from app.services.automations.events import EVENT_APPOINTMENT_BOOKED, emit_automation_event
from app.services.calendar.ics import CalendarInvite, appointment_uid, render_invite
from app.services.email import (
    send_appointment_booked_notification,
    send_appointment_confirmation_to_attendee,
)
from app.services.google_calendar import GoogleCalendarError
from app.services.idempotency import derive_outbound_key
from app.services.leads.funnel_transitions import mark_contact_booked
from app.utils.background_tasks import spawn_background_task
from app.utils.meeting_urls import meeting_provider_name, zoom_meeting_id_from_url
from app.utils.timezones import DEFAULT_WORKSPACE_TIMEZONE, workspace_timezone_name

logger = structlog.get_logger()

DEFAULT_TIMEZONE = DEFAULT_WORKSPACE_TIMEZONE
DEFAULT_SERVICE_SUMMARY = "Appointment"


async def finalize_booking(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact: Contact,
    scheduled_at: datetime,
    duration_minutes: int,
    agent: Agent | None = None,
    campaign_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    notes: str | None = None,
    service_type: str | None = None,
    assigned_staff_id: uuid.UUID | None = None,
    required_skill: str | None = None,
    notify: bool = True,
    send_customer_sms: bool = True,
) -> Appointment:
    """Persist a booked appointment and trigger its downstream notifications.

    ``scheduled_at`` must be timezone-aware; a naive value means the caller lost
    the customer's zone somewhere upstream and the appointment would silently
    land at the wrong hour.

    Pass ``assigned_staff_id`` when the caller already ran staff routing for this
    booking. Re-resolving would bump the round-robin counter a second time and
    could land the appointment on a different rep than the one whose availability
    the customer was offered.

    Commits, because the notifications that follow must never describe an
    appointment that a later rollback erases.
    """
    if scheduled_at.tzinfo is None:
        msg = "scheduled_at must be timezone-aware; a naive value loses the customer's timezone"
        raise ValueError(msg)

    # Read the id once, up front. ``db.rollback()`` in the recovery path below
    # expires every instance in the session, and re-reading ``contact.id`` after
    # that triggers implicit IO, which asyncio SQLAlchemy refuses with
    # ``MissingGreenlet`` — turning a recoverable race into a crash.
    contact_id = contact.id

    existing = await _find_duplicate(db, workspace_id, contact_id, scheduled_at)
    if existing is not None:
        logger.info(
            "appointment_already_booked",
            appointment_id=existing.id,
            contact_id=contact_id,
            scheduled_at=scheduled_at.isoformat(),
        )
        if notify and existing.sync_status != "synced":
            spawn_background_task(
                deliver_booking_notifications(
                    existing.id,
                    send_customer_sms=send_customer_sms,
                    send_notifications=False,
                ),
                name=f"booking_calendar_retry:{existing.id}",
            )
        return existing

    staff_id = assigned_staff_id
    if staff_id is None:
        staff = await _resolve_staff(db, agent=agent, required_skill=required_skill)
        staff_id = staff.id if staff is not None else None

    appointment = Appointment(
        workspace_id=workspace_id,
        contact_id=contact_id,
        agent_id=agent.id if agent is not None else None,
        campaign_id=campaign_id,
        message_id=message_id,
        bookable_staff_id=staff_id,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        status=AppointmentStatus.SCHEDULED,
        service_type=service_type,
        notes=notes,
        sync_status="pending",
    )
    db.add(appointment)
    try:
        await db.flush()
        await mark_contact_booked(db, contact)
        await _cancel_acquisition_funnel_executions(
            db,
            workspace_id=workspace_id,
            contact_id=contact_id,
        )
        await emit_automation_event(
            db,
            workspace_id=workspace_id,
            event_type=EVENT_APPOINTMENT_BOOKED,
            contact_id=contact_id,
            payload={
                "appointment_id": appointment.id,
                "service_type": service_type,
                "scheduled_at": scheduled_at.isoformat(),
                "bookable_staff_id": str(staff_id) if staff_id is not None else None,
                "sync_status": appointment.sync_status,
            },
        )
        await db.commit()
    except IntegrityError:
        # Lost the race: another booking for this contact+slot committed between
        # the duplicate check above and this insert, and the partial unique index
        # ``uq_appointments_live_contact_slot`` rejected the second row. That is
        # the index doing its job — the customer does have a booking, so return
        # the row that won instead of failing a booking they already confirmed.
        await db.rollback()
        winner = await _find_duplicate(db, workspace_id, contact_id, scheduled_at)
        if winner is None:
            # The violation was something else; do not disguise it as idempotency.
            # Surfacing it is correct: we have no booking to hand back.
            raise
        logger.info(
            "appointment_duplicate_rejected_by_index",
            appointment_id=winner.id,
            contact_id=contact_id,
            scheduled_at=scheduled_at.isoformat(),
        )
        return winner
    await db.refresh(appointment)

    logger.info(
        "appointment_finalized",
        appointment_id=appointment.id,
        workspace_id=str(workspace_id),
        contact_id=contact_id,
        assigned_staff_id=str(staff_id) if staff_id is not None else None,
        scheduled_at=appointment.scheduled_at.isoformat(),
    )

    if notify:
        spawn_background_task(
            deliver_booking_notifications(appointment.id, send_customer_sms=send_customer_sms),
            name=f"booking_notifications:{appointment.id}",
        )

    return appointment


async def _cancel_acquisition_funnel_executions(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
) -> None:
    """Complete only explicitly identified acquisition runs for this contact."""
    acquisition_ids = select(Automation.id).where(
        Automation.workspace_id == workspace_id,
        Automation.trigger_config["funnel_id"].astext.is_not(None),
    )
    await db.execute(
        update(AutomationExecution)
        .where(
            AutomationExecution.automation_id.in_(acquisition_ids),
            AutomationExecution.contact_id == contact_id,
            AutomationExecution.status.in_(["pending", "running", "scheduled"]),
        )
        .values(
            status="completed",
            scheduled_for=None,
            executed_at=datetime.now(UTC),
            error="Acquisition funnel stopped after appointment booking",
        )
    )


async def _find_duplicate(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int,
    scheduled_at: datetime,
) -> Appointment | None:
    """Return an existing booking for this contact at this exact time, if any.

    The approval handler commits the appointment before the pending action is
    marked executed, so a retry after a mid-flight failure would otherwise book
    the same slot twice — two rows, two confirmation texts, two invites. Agents
    re-calling the tool after a timeout hit the same guard.
    """
    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.workspace_id == workspace_id,
            Appointment.contact_id == contact_id,
            Appointment.scheduled_at == scheduled_at,
            Appointment.status == AppointmentStatus.SCHEDULED,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _resolve_staff(
    db: AsyncSession,
    *,
    agent: Agent | None,
    required_skill: str | None,
) -> BookableStaff | None:
    """Pick the rep for this booking, or ``None`` when routing yields nobody.

    Never lets a routing failure sink a confirmed booking — an unassigned
    appointment is recoverable in the dashboard, a lost one is not.
    """
    if agent is None:
        return None

    try:
        from app.services.calendar.staff_assignment import resolve_staff_for_booking

        return await resolve_staff_for_booking(
            db,
            agent=agent,
            required_skill=required_skill,
            commit=False,
        )
    except Exception:  # noqa: BLE001 - assignment is best-effort
        logger.exception("staff_assignment_failed", agent_id=str(agent.id))
        return None


async def deliver_booking_notifications(
    appointment_id: int,
    *,
    send_customer_sms: bool = True,
    send_notifications: bool = True,
) -> None:
    """Send customer and rep booking notifications.

    ``send_customer_sms`` is false for a live SMS tool call because the tool's
    single natural-language reply is itself the confirmation. Other booking paths
    keep the deterministic lifecycle text. Customer and rep emails are independent
    so either can succeed when the other provider call fails.
    """
    log = logger.bind(appointment_id=appointment_id)

    async with AsyncSessionLocal() as db:
        appointment = await db.get(Appointment, appointment_id)
        if appointment is None:
            log.warning("booking_notifications_appointment_missing")
            return

        contact = await db.get(Contact, appointment.contact_id)
        if contact is None:
            log.warning("booking_notifications_contact_missing")
            return

        workspace = await db.get(Workspace, appointment.workspace_id)
        agent = (
            await db.get(Agent, appointment.agent_id) if appointment.agent_id is not None else None
        )
        staff = (
            await db.get(BookableStaff, appointment.bookable_staff_id)
            if appointment.bookable_staff_id is not None
            else None
        )

        # Sync first so every confirmation reflects provider truth: a successful
        # video call includes its Zoom/Meet link; a failure promises follow-up.
        await sync_appointment_external_events(
            db,
            appointment=appointment,
            contact=contact,
            workspace=workspace,
            staff=staff,
            log=log,
        )
        if send_notifications and send_customer_sms:
            await _send_customer_confirmation(
                db,
                appointment=appointment,
                contact=contact,
                workspace=workspace,
                agent=agent,
                log=log,
            )
        if send_notifications:
            await _send_attendee_confirmation(
                appointment=appointment,
                contact=contact,
                workspace=workspace,
                agent=agent,
                log=log,
            )
            await _send_rep_invite(
                db,
                appointment=appointment,
                contact=contact,
                workspace=workspace,
                staff=staff,
                log=log,
            )


async def _send_customer_confirmation(
    db: AsyncSession,
    *,
    appointment: Appointment,
    contact: Contact,
    workspace: Workspace | None,
    agent: Agent | None,
    log: structlog.BoundLogger,
) -> None:
    """Text the customer that their appointment is confirmed.

    ``send_lifecycle_sms`` owns the TCPA opt-out check and from-number
    resolution, and never raises.
    """
    body = build_confirmation_body(
        contact=contact,
        appointment=appointment,
        workspace=workspace,
        agent=agent,
    )
    await send_lifecycle_sms(
        db=db,
        workspace_id=appointment.workspace_id,
        contact=contact,
        agent=agent,
        body_text=body,
        # Keyed on the appointment so a retry or a double-fired hook cannot text
        # the same customer twice about the same booking.
        idempotency_scope="local_booking_confirmation_sms",
        idempotency_parts=(appointment.id,),
    )
    log.info("booking_confirmation_sms_dispatched", contact_id=contact.id)


async def _send_attendee_confirmation(
    *,
    appointment: Appointment,
    contact: Contact,
    workspace: Workspace | None,
    agent: Agent | None,
    log: structlog.BoundLogger,
) -> None:
    """Email the customer their confirmation plus a calendar invite.

    Skipped when the agent has confirmation emails off or we have no address to
    send to. Fully guarded: this is the newest of the three notifications, and a
    failure here must not cost the customer their SMS or the rep their invite.
    """
    if agent is not None and not agent.confirmation_email_enabled:
        return
    if not contact.email:
        log.info("attendee_confirmation_skipped_no_email", contact_id=contact.id)
        return

    try:
        contact_name = contact.full_name or "there"
        business_name = workspace.name if workspace is not None else ""
        location = _meeting_method(contact, appointment)

        summary = (
            f"{appointment.service_type or DEFAULT_SERVICE_SUMMARY} — {business_name}"
        ).strip(" —")
        invite = CalendarInvite(
            uid=appointment_uid(appointment.id),
            starts_at=appointment.scheduled_at,
            duration_minutes=appointment.duration_minutes,
            summary=summary,
            description=_invite_description(contact, appointment),
            location=location or "",
            organizer_email=_organizer_email(),
            organizer_name=business_name or None,
            attendee_email=contact.email,
            attendee_name=contact.full_name or None,
        )

        await send_appointment_confirmation_to_attendee(
            to_email=contact.email,
            contact_name=contact_name,
            business_name=business_name,
            appointment_time=appointment.scheduled_at,
            service_type=appointment.service_type,
            location=location or None,
            meeting_url=appointment.meeting_url,
            sync_status=appointment.sync_status,
            timezone=_workspace_timezone(workspace),
            ics_content=render_invite(invite),
            idempotency_key=derive_outbound_key("attendee_booking_invite_email", appointment.id),
        )
        log.info("attendee_confirmation_email_dispatched", contact_id=contact.id)
    except Exception:  # noqa: BLE001 - notification must not break booking
        log.exception("attendee_confirmation_email_failed")


async def sync_appointment_external_events(
    db: AsyncSession,
    *,
    appointment: Appointment,
    contact: Contact,
    workspace: Workspace | None,
    staff: BookableStaff | None,
    log: structlog.BoundLogger,
) -> None:
    """Create Zoom first, then mirror the booking to the rep's Google Calendar.

    Provider sync follows the durable local appointment but precedes lifecycle
    copy, so every notification reflects the resulting Zoom/Meet URL or failure.
    """
    if appointment.google_calendar_event_id and appointment.sync_status == "synced":
        return
    if staff is None or staff.user_id is None:
        appointment.sync_status = "not_connected"
        appointment.sync_error = "Assigned staff does not have a login-linked calendar"
        await db.commit()
        return

    try:
        zoom_created = await _ensure_zoom_meeting(
            db,
            appointment=appointment,
            workspace=workspace,
            staff=staff,
            log=log,
        )
        from app.services.google_calendar import create_event

        event = await create_event(
            db,
            user_id=staff.user_id,
            summary=(
                f"{appointment.service_type or DEFAULT_SERVICE_SUMMARY} — "
                f"{contact.full_name or 'Customer'}"
            ),
            description=_invite_description(contact, appointment),
            location=_meeting_method(contact, appointment, include_failure=False),
            starts_at=appointment.scheduled_at,
            duration_minutes=appointment.duration_minutes,
            timezone=_workspace_timezone(workspace),
            attendee_email=contact.email,
            attendee_name=contact.full_name or None,
            conference=appointment.service_type == "video_call" and not zoom_created,
            event_id=f"tribunalappointment{appointment.id}",
        )
        appointment.google_calendar_event_id = event.event_id
        appointment.google_calendar_event_url = event.html_link
        if appointment.service_type == "video_call" and not appointment.meeting_url:
            appointment.meeting_url = event.meet_link
        appointment.sync_status = "synced"
        appointment.sync_error = None
        appointment.last_synced_at = datetime.now(UTC)
        await db.commit()
        log.info(
            "google_calendar_event_created",
            user_id=staff.user_id,
            event_id=event.event_id,
            video_provider=(
                meeting_provider_name(appointment.meeting_url)
                if appointment.service_type == "video_call"
                else None
            ),
        )
    except GoogleCalendarError as exc:
        error_text = str(exc)
        appointment.sync_status = (
            "not_connected" if "not connected" in error_text.lower() else "failed"
        )
        appointment.sync_error = error_text[:2000]
        await db.commit()
        log.warning("google_calendar_event_not_created", error=error_text)
    except Exception:  # noqa: BLE001 - CRM booking must survive provider failures
        appointment.sync_status = "failed"
        appointment.sync_error = "Google Calendar synchronization failed"
        await db.commit()
        log.exception("google_calendar_event_create_failed")


async def _ensure_zoom_meeting(
    db: AsyncSession,
    *,
    appointment: Appointment,
    workspace: Workspace | None,
    staff: BookableStaff,
    log: structlog.BoundLogger,
) -> bool:
    """Create and durably save one Zoom meeting for the configured host."""
    if appointment.service_type != "video_call" or staff.user_id is None:
        return False
    if zoom_meeting_id_from_url(appointment.meeting_url):
        return True

    from app.services.zoom import (
        ZoomError,
        create_meeting,
        zoom_configured_for_user,
    )

    if not await zoom_configured_for_user(db, user_id=staff.user_id):
        return False
    try:
        meeting = await create_meeting(
            starts_at=appointment.scheduled_at,
            duration_minutes=appointment.duration_minutes,
            timezone=_workspace_timezone(workspace),
            topic=f"{workspace.name if workspace else 'Business'} consultation",
            agenda=f"CRM appointment {appointment.id}",
        )
    except ZoomError:
        log.warning("zoom_meeting_not_created_using_meet_fallback")
        return False
    except Exception:  # noqa: BLE001 - Google Meet remains the safe fallback
        log.exception("zoom_meeting_create_failed_using_meet_fallback")
        return False

    appointment.meeting_url = meeting.join_url
    # Persist before Google sync so a Google retry cannot duplicate a Zoom meeting.
    await db.commit()
    log.info("zoom_meeting_created", appointment_id=appointment.id)
    return True


async def _send_rep_invite(
    db: AsyncSession,
    *,
    appointment: Appointment,
    contact: Contact,
    workspace: Workspace | None,
    staff: BookableStaff | None,
    log: structlog.BoundLogger,
) -> None:
    """Email the assigned rep a calendar invite for the booking."""
    try:
        recipient = await _resolve_invite_recipient(db, appointment.workspace_id, staff)
        if recipient is None:
            log.warning("booking_invite_no_recipient")
            return

        to_email, to_name = recipient
        timezone = _workspace_timezone(workspace)
        contact_name = contact.full_name or "Customer"

        invite = CalendarInvite(
            uid=appointment_uid(appointment.id),
            starts_at=appointment.scheduled_at,
            duration_minutes=appointment.duration_minutes,
            summary=f"{appointment.service_type or DEFAULT_SERVICE_SUMMARY} — {contact_name}",
            description=_invite_description(contact, appointment),
            location=_meeting_method(contact, appointment) or "",
            # The sending identity organizes; the rep attends. Naming the rep as
            # both makes it a self-organized event, and clients like Gmail then
            # hide the Accept/Decline controls.
            organizer_email=_organizer_email(),
            organizer_name=workspace.name if workspace is not None else None,
            attendee_email=to_email,
            attendee_name=to_name,
        )

        await send_appointment_booked_notification(
            to_email=to_email,
            owner_name=to_name,
            contact_name=contact_name,
            contact_phone=contact.phone_number or "",
            appointment_time=appointment.scheduled_at,
            calendar_event_url=appointment.google_calendar_event_url,
            timezone=timezone,
            ics_content=render_invite(invite),
            idempotency_key=derive_outbound_key("local_booking_invite_email", appointment.id),
        )
        log.info("booking_invite_email_dispatched", to_email=to_email)
    except Exception:  # noqa: BLE001 - notification must not break booking
        log.exception("booking_invite_email_failed")


async def _resolve_invite_recipient(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    staff: BookableStaff | None,
) -> tuple[str, str] | None:
    """Return ``(email, name)`` for the invite.

    Prefers the assigned rep. Falls back to the workspace owner, which is the
    live path for every workspace that has not built a staff pool yet.
    """
    if staff is not None and staff.email:
        return staff.email, staff.name
    if staff is not None and staff.user_id is not None:
        user = await db.get(User, staff.user_id)
        if user is not None:
            return user.email, user.full_name or staff.name

    result = await db.execute(
        select(User.email, User.full_name)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.role == "owner",
        )
        .order_by(WorkspaceMembership.created_at.asc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None
    return row.email, row.full_name or row.email


def _organizer_email() -> str:
    """Return the address the invite is organized by.

    Falls back to a namespaced no-reply so the ORGANIZER property is never empty
    — clients drop an invite that names no organizer.
    """
    from app.core.config import settings

    return settings.resend_from_email or "no-reply@the-tribunal.app"


def _workspace_timezone(workspace: Workspace | None) -> str:
    """Return the workspace's IANA zone, defaulting to Eastern."""
    return workspace_timezone_name(workspace)


def format_contact_address(contact: Contact) -> str:
    """Render the contact's mailing address as a single line.

    Partial addresses are common on reactivated leads, so this emits whatever is
    present rather than requiring the full set.
    """
    street = " ".join(filter(None, [contact.address_line1, contact.address_line2])).strip()
    locality = ", ".join(filter(None, [street, contact.address_city, contact.address_state]))
    return " ".join(filter(None, [locality, contact.address_zip])).strip()


def _meeting_method(
    contact: Contact,
    appointment: Appointment,
    *,
    include_failure: bool = True,
) -> str | None:
    """Return only a real call method; provider failure never fabricates a URL."""
    if appointment.service_type == "phone_call":
        return f"Phone call: {contact.phone_number}" if contact.phone_number else "Phone call"
    if appointment.service_type == "video_call":
        if appointment.meeting_url:
            return f"{meeting_provider_name(appointment.meeting_url)}: {appointment.meeting_url}"
        if include_failure:
            return "Video link pending — operator follow-up required"
        return None
    return format_contact_address(contact) or None


def _invite_description(contact: Contact, appointment: Appointment) -> str:
    """Build call details and contact context for customer/rep calendars."""
    parts = [f"Customer: {contact.full_name or 'Customer'}"]
    method = _meeting_method(contact, appointment)
    if method:
        parts.append(f"Meeting method: {method}")
    if contact.phone_number:
        parts.append(f"Phone: {contact.phone_number}")
    if contact.email:
        parts.append(f"Email: {contact.email}")
    address = format_contact_address(contact)
    if address:
        parts.append(f"Address: {address}")
    if appointment.notes:
        parts.append(f"Notes: {appointment.notes}")
    parts.append("Booked automatically by your AI agent.")
    return "\n".join(parts)


async def load_agent(db: AsyncSession, agent_id: uuid.UUID | None) -> Agent | None:
    """Fetch an agent by id, tolerating a missing/None id."""
    if agent_id is None:
        return None
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()
