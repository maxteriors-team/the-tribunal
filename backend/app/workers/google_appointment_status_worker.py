"""Time-based completion for Google-booked appointments.

Google Calendar has no ``MEETING_ENDED`` webhook (Cal.com's completion signal),
so this worker transitions Google appointments from SCHEDULED to COMPLETED once
their end time plus a grace window has passed. Completion drives the same
downstream effects Cal.com's ``handle_meeting_ended`` did on the attended path:
campaign guarantee tracking, a "showed-up" contact tag, and a review request.

No-shows are not auto-detected (Google can't tell us attendance); a human/agent
flags NO_SHOW, and the existing no-show re-engagement worker handles it. Only
Google-provider appointments are touched — Cal.com bookings still complete via
their webhook.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.services.calendar.google.oauth import PROVIDER
from app.services.campaigns.guarantee_tracker import increment_completed_and_check_guarantee
from app.services.tags import TagService
from app.workers.base import BaseWorker, WorkerRegistry


class GoogleAppointmentStatusWorker(BaseWorker):
    """Mark elapsed Google appointments COMPLETED and fire completion effects."""

    POLL_INTERVAL_SECONDS = settings.google_appointment_status_poll_interval
    COMPONENT_NAME = "google_appointment_status"
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        grace = timedelta(minutes=settings.google_appointment_grace_minutes)
        now = datetime.now(UTC)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Appointment).where(
                    Appointment.calendar_provider == PROVIDER,
                    Appointment.status == AppointmentStatus.SCHEDULED,
                    Appointment.scheduled_at < now,
                )
            )
            appointments = list(result.scalars().all())

            completed = 0
            for appointment in appointments:
                if not appointment_is_due(
                    appointment.scheduled_at, appointment.duration_minutes, now, grace
                ):
                    continue
                await self._complete(db, appointment, now)
                completed += 1

            await db.commit()

        if completed:
            self.record_items_processed(completed)
            self.logger.info("google_appointments_completed", completed=completed)

    async def _complete(self, db: object, appointment: Appointment, now: datetime) -> None:
        log = self.logger.bind(appointment_id=appointment.id)
        appointment.status = AppointmentStatus.COMPLETED
        appointment.sync_status = "synced"
        appointment.last_synced_at = now

        # Contact lifecycle: attended.
        try:
            contact_result = await db.execute(  # type: ignore[attr-defined]
                select(Contact).where(Contact.id == appointment.contact_id)
            )
            contact = contact_result.scalar_one_or_none()
            if contact is not None:
                await TagService(db).add_tag_to_contact(  # type: ignore[arg-type]
                    workspace_id=contact.workspace_id,
                    contact_id=contact.id,
                    name="showed-up",
                )
                contact.last_appointment_status = "completed"
                db.add(contact)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - side effect must not abort completion
            log.exception("google_completion_contact_tag_failed")

        # Campaign guarantee tracking.
        if appointment.campaign_id:
            try:
                await increment_completed_and_check_guarantee(db, appointment.campaign_id, log)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                log.exception("google_completion_guarantee_failed")

        # Review request (no-ops unless the workspace has the engine enabled).
        try:
            from app.services.reviews import ReviewService

            await ReviewService(db).enqueue_for_appointment(appointment)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            log.exception("google_completion_review_enqueue_failed")

        log.info("google_appointment_completed", appointment_id=appointment.id)


def appointment_is_due(
    scheduled_at: datetime,
    duration_minutes: int,
    now: datetime,
    grace: timedelta,
) -> bool:
    """Return whether an appointment's end time plus grace has passed."""
    end = scheduled_at + timedelta(minutes=duration_minutes)
    return end + grace <= now


_registry = WorkerRegistry(GoogleAppointmentStatusWorker)
start_google_appointment_status_worker = _registry.start
stop_google_appointment_status_worker = _registry.stop
get_google_appointment_status_worker = _registry.get
