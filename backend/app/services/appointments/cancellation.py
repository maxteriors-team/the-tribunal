"""Cancel a contact's upcoming appointments.

The AI agents could book but never cancel. When a customer texted "cancel", the
model had no tool to call, so it did the only thing it could: it *said* the
appointment was cancelled and moved on. The row stayed ``scheduled``, and the
reminder worker — which correctly filters on status — kept texting reminders for
a meeting the customer had already called off. The customer sees a confirmed
cancellation followed by reminders, which reads as either incompetence or a
company that ignores what they say.

This module is the counterpart to ``booking_finalizer``: the single place an
appointment stops being real.

Every *future* scheduled appointment for the contact is cancelled, not just the
next one. An SMS thread is one-to-one with a contact, so "cancel" means "I am
not attending the thing you keep texting me about" — and if a double-booking
ever leaves two rows on the same slot, cancelling only the first would leave its
twin firing reminders, which is the bug this module exists to kill.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus
from app.models.bookable_staff import BookableStaff
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.tags import TagService
from app.utils.timezones import resolve_workspace_timezone

logger = structlog.get_logger()

__all__ = ["CancellationResult", "CancelledAppointment", "cancel_upcoming_appointments"]

CANCELLED_TAG = "appointment-cancelled"


@dataclass(frozen=True, slots=True)
class CancelledAppointment:
    """One appointment that was moved out of ``scheduled``."""

    appointment_id: int
    scheduled_at: datetime
    local_label: str


@dataclass(frozen=True, slots=True)
class CancellationResult:
    """Outcome of a cancellation request.

    ``cancelled`` is empty when the contact had nothing upcoming. That is not an
    error — it is the answer to "please cancel", and the caller should say so
    rather than inventing a cancellation.
    """

    cancelled: tuple[CancelledAppointment, ...]

    @property
    def count(self) -> int:
        return len(self.cancelled)


async def cancel_upcoming_appointments(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    reason: str | None = None,
    cancelled_by: str = "customer",
) -> CancellationResult:
    """Cancel every future scheduled appointment for ``contact_id``.

    Past appointments are left alone: a meeting that already happened is history,
    and rewriting it to ``cancelled`` would corrupt attendance reporting.

    Commits, so the reply the agent sends can never describe a cancellation that
    a later rollback erases — the same guarantee ``finalize_booking`` makes in
    the other direction.
    """
    now = datetime.now(UTC)

    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.workspace_id == workspace_id,
            Appointment.contact_id == contact_id,
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.scheduled_at > now,
        )
        .order_by(Appointment.scheduled_at)
    )
    appointments = list(result.scalars().all())

    if not appointments:
        logger.info(
            "appointment_cancel_nothing_upcoming",
            workspace_id=str(workspace_id),
            contact_id=contact_id,
        )
        return CancellationResult(cancelled=())

    workspace = await db.get(Workspace, workspace_id)
    tzinfo = resolve_workspace_timezone(workspace)

    staff_ids = {
        appointment.bookable_staff_id
        for appointment in appointments
        if appointment.bookable_staff_id is not None
    }
    staff_by_id: dict[uuid.UUID, BookableStaff] = {}
    if staff_ids:
        staff_result = await db.execute(
            select(BookableStaff).where(BookableStaff.id.in_(staff_ids))
        )
        staff_by_id = {staff.id: staff for staff in staff_result.scalars().all()}

    cancelled: list[CancelledAppointment] = []
    from app.services.google_calendar import GoogleCalendarError, delete_event

    for appointment in appointments:
        appointment.status = AppointmentStatus.CANCELLED
        appointment.notes = _append_cancellation_note(appointment.notes, reason, cancelled_by, now)
        appointment.last_synced_at = now
        appointment.sync_error = None
        if appointment.google_calendar_event_id and appointment.bookable_staff_id:
            staff = staff_by_id.get(appointment.bookable_staff_id)
            if staff is not None and staff.user_id is not None:
                try:
                    await delete_event(
                        db,
                        user_id=staff.user_id,
                        event_id=appointment.google_calendar_event_id,
                    )
                    appointment.sync_status = "synced"
                except GoogleCalendarError as exc:
                    appointment.sync_status = "failed"
                    appointment.sync_error = str(exc)[:2000]
            else:
                appointment.sync_status = "failed"
                appointment.sync_error = "Assigned calendar owner was not found"
        else:
            appointment.sync_status = "synced"

        local_dt = appointment.scheduled_at.astimezone(tzinfo)
        # Workspace-local, matching the wording of the confirmation and reminder
        # texts so the customer never sees two different hours for one meeting.
        label = f"{local_dt.strftime('%A, %B %-d')} at {local_dt.strftime('%-I:%M %p')}"
        cancelled.append(
            CancelledAppointment(
                appointment_id=appointment.id,
                scheduled_at=appointment.scheduled_at,
                local_label=label,
            )
        )

    contact = await db.get(Contact, contact_id)
    if contact is not None:
        contact.last_appointment_status = "cancelled"
        db.add(contact)
        try:
            await TagService(db).add_tag_to_contact(
                workspace_id=workspace_id,
                contact_id=contact_id,
                name=CANCELLED_TAG,
            )
        except Exception:  # noqa: BLE001 - tagging must never block the cancellation
            logger.exception("appointment_cancel_tagging_failed", contact_id=contact_id)

    await db.commit()

    logger.info(
        "appointments_cancelled",
        workspace_id=str(workspace_id),
        contact_id=contact_id,
        count=len(cancelled),
        appointment_ids=[item.appointment_id for item in cancelled],
        cancelled_by=cancelled_by,
    )

    return CancellationResult(cancelled=tuple(cancelled))


def _append_cancellation_note(
    existing: str | None,
    reason: str | None,
    cancelled_by: str,
    when: datetime,
) -> str:
    """Record who cancelled and why in the appointment's notes.

    Kept in ``notes`` rather than a dedicated column so the audit trail ships
    without a migration on a table that holds live customer bookings.
    """
    stamp = when.strftime("%Y-%m-%d %H:%M UTC")
    line = f"[{stamp}] Cancelled by {cancelled_by}."
    if reason:
        line = f"{line} Reason: {reason.strip()}"
    return f"{existing}\n{line}" if existing else line
