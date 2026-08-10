"""The single place an AI-booked appointment becomes real.

Three paths book appointments — the voice tool executor, the text tool executor,
and the HITL approval handler — and each one used to hand-roll its own "write the
row" step. That duplication is exactly how the approval path shipped without
writing a row at all: the booking reported success and landed on no calendar.

Everything that must happen when a booking succeeds lives here:

1. **Rep assignment** — resolve the bookable staff member via the agent's routing
   strategy so an appointment has an owner instead of sitting unassigned.
2. **The appointment row** — the CRM table is the source of truth for scheduling.
3. **Customer confirmation SMS** — previously only sent by the Cal.com webhook,
   which never fires for a local booking, so customers got no confirmation.
4. **Calendar invite to the rep** — an ``.ics`` attachment so the appointment
   shows up in the calendar they actually watch.

Notifications run *after* commit and are fire-and-forget: a texting or email
outage must never roll back a confirmed booking, and we must never text a
customer about an appointment whose transaction was rolled back.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.bookable_staff import BookableStaff
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.appointments.lifecycle_sms import build_confirmation_body, send_lifecycle_sms
from app.services.calendar.ics import CalendarInvite, appointment_uid, render_invite
from app.services.email import send_appointment_booked_notification
from app.services.idempotency import derive_outbound_key
from app.utils.background_tasks import spawn_background_task
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
    calcom_booking_uid: str | None = None,
    calcom_booking_id: int | None = None,
    calcom_event_type_id: int | None = None,
    notify: bool = True,
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
        calcom_booking_uid=calcom_booking_uid,
        calcom_booking_id=calcom_booking_id,
        calcom_event_type_id=calcom_event_type_id,
        sync_status="synced",
        last_synced_at=datetime.now(scheduled_at.tzinfo),
    )
    db.add(appointment)
    try:
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
            # The violation was something else (a duplicate Cal.com uid, say).
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
            deliver_booking_notifications(appointment.id),
            name=f"booking_notifications:{appointment.id}",
        )

    return appointment


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


async def deliver_booking_notifications(appointment_id: int) -> None:
    """Send the customer confirmation SMS and the rep's calendar invite.

    Runs on its own session because it is spawned after the caller's session has
    committed (and may already be closed). Each side is independently guarded so
    a failing SMS provider still lets the calendar invite through, and vice versa.
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

        await _send_customer_confirmation(
            db,
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
            # Calendar apps turn LOCATION into a tap-to-navigate link, which is
            # the whole job for a trades rep driving to the address.
            location=format_contact_address(contact),
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

    from app.api.webhooks.calcom_events import get_workspace_owner

    return await get_workspace_owner(db, workspace_id)


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


def _invite_description(contact: Contact, appointment: Appointment) -> str:
    """Build the invite body the rep reads on their phone before knocking."""
    parts = [f"Customer: {contact.full_name or 'Customer'}"]
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
