"""Contact-side effects of an appointment's attendance outcome.

Marking a customer attended or absent is not just a column on ``appointments``:
three shipped features read the *contact* fields this writes.

- ``app.workers.noshow_reengagement_worker`` selects on
  ``contacts.last_appointment_status == "no_show"`` **and** the ``no-show`` tag.
- The ``no_show`` automation trigger matches the same tag.
- ``contacts.noshow_count`` feeds nudges and lead scoring.

Cal.com's ``meeting_ended`` webhook used to be the only writer, so an in-app
"mark no-show" button that only set ``appointments.status`` would produce a
no-show invisible to all three. This module is the single place those effects
live, called from both the webhook (``app.api.webhooks.calcom_handlers``) and
``AppointmentService.update_appointment``.

Idempotent by design: ``noshow_count`` is incremented only on the *transition*
into ``no_show``, so re-marking an already-absent appointment (a replayed
webhook, a double-click) never inflates the counter.

Flushes nothing and commits nothing — the caller owns the transaction.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.services.tags.tag_service import TagService

logger = structlog.get_logger()

__all__ = [
    "ATTENDANCE_STATUSES",
    "NO_SHOW_TAG",
    "SHOWED_UP_TAG",
    "record_attendance_outcome",
]

# Lifecycle tags the automation trigger and the re-engagement worker match on.
NO_SHOW_TAG = "no-show"
SHOWED_UP_TAG = "showed-up"

# The two outcomes that decide a show-up rate. ``scheduled`` is undecided and
# ``cancelled`` is a call-off, not an absence — neither writes contact state.
ATTENDANCE_STATUSES = frozenset({AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW})


async def record_attendance_outcome(
    db: AsyncSession,
    appointment: Appointment,
    *,
    previous_status: str | None,
) -> Contact | None:
    """Apply the contact-side effects of ``appointment``'s attendance outcome.

    Args:
        db: Active session; rows are mutated but **not** committed.
        appointment: The appointment whose ``status`` was just decided.
        previous_status: The status before the change, used to keep
            ``noshow_count`` idempotent across replays and re-marks.

    Returns:
        The updated :class:`Contact`, or ``None`` when the new status is not an
        attendance outcome or the contact row is missing.
    """
    new_status = appointment.status
    if new_status not in ATTENDANCE_STATUSES:
        return None

    result = await db.execute(select(Contact).where(Contact.id == appointment.contact_id))
    contact = result.scalar_one_or_none()
    if contact is None:
        logger.warning(
            "attendance_contact_missing",
            appointment_id=appointment.id,
            contact_id=appointment.contact_id,
        )
        return None

    is_no_show = new_status == AppointmentStatus.NO_SHOW
    tags = TagService(db)

    if is_no_show:
        await tags.add_tag_to_contact(
            workspace_id=contact.workspace_id,
            contact_id=contact.id,
            name=NO_SHOW_TAG,
        )
        contact.last_appointment_status = AppointmentStatus.NO_SHOW.value
        # Count the transition, not the marking: a replayed webhook or a second
        # click must not make one absence look like two.
        if previous_status != AppointmentStatus.NO_SHOW:
            contact.noshow_count = (contact.noshow_count or 0) + 1
    else:
        await tags.add_tag_to_contact(
            workspace_id=contact.workspace_id,
            contact_id=contact.id,
            name=SHOWED_UP_TAG,
        )
        contact.last_appointment_status = AppointmentStatus.COMPLETED.value

    db.add(contact)
    logger.info(
        "attendance_recorded",
        appointment_id=appointment.id,
        contact_id=contact.id,
        status=str(new_status),
        previous_status=str(previous_status) if previous_status else None,
        noshow_count=contact.noshow_count,
    )
    return contact
