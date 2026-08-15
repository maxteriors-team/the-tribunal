"""Best-effort lifecycle synchronization for Google events and Zoom meetings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.bookable_staff import BookableStaff
from app.models.workspace import Workspace
from app.services.google_calendar import GoogleCalendarError
from app.services.zoom import ZoomError
from app.utils.meeting_urls import zoom_meeting_id_from_url
from app.utils.timezones import workspace_timezone_name


async def update_external_events(
    db: AsyncSession,
    *,
    appointment: Appointment,
    workspace: Workspace | None,
    log: Any,
) -> None:
    """Update every provider linked to a rescheduled local appointment."""
    errors: list[str] = []
    attempted = False
    timezone = workspace_timezone_name(workspace)
    zoom_meeting_id = zoom_meeting_id_from_url(appointment.meeting_url)

    if zoom_meeting_id:
        attempted = True
        try:
            from app.services.zoom import update_meeting

            await update_meeting(
                meeting_id=zoom_meeting_id,
                starts_at=appointment.scheduled_at,
                duration_minutes=appointment.duration_minutes,
                timezone=timezone,
            )
            log.info("zoom_meeting_updated", appointment_id=appointment.id)
        except ZoomError:
            errors.append("Zoom meeting update failed")
            log.warning("zoom_meeting_update_failed", appointment_id=appointment.id)
        except Exception:  # noqa: BLE001 - local reschedule must survive provider failure
            errors.append("Zoom meeting update failed")
            log.exception("zoom_meeting_update_failed", appointment_id=appointment.id)

    if appointment.google_calendar_event_id:
        attempted = True
        user_id = await _calendar_owner_user_id(db, appointment)
        if user_id is None:
            errors.append("Assigned staff calendar is not connected")
        else:
            try:
                from app.services.google_calendar import update_event_time

                await update_event_time(
                    db,
                    user_id=user_id,
                    event_id=appointment.google_calendar_event_id,
                    starts_at=appointment.scheduled_at,
                    duration_minutes=appointment.duration_minutes,
                    timezone=timezone,
                )
                log.info("google_calendar_event_updated", appointment_id=appointment.id)
            except GoogleCalendarError:
                errors.append("Google Calendar update failed")
                log.warning("google_calendar_event_update_failed", appointment_id=appointment.id)
            except Exception:  # noqa: BLE001 - local reschedule must survive provider failure
                errors.append("Google Calendar update failed")
                log.exception("google_calendar_event_update_failed", appointment_id=appointment.id)

    if not attempted:
        return
    if errors:
        appointment.sync_status = "failed"
        appointment.sync_error = "; ".join(errors)
        return
    appointment.sync_status = "synced"
    appointment.sync_error = None
    appointment.last_synced_at = datetime.now(UTC)


async def delete_external_events(
    db: AsyncSession,
    *,
    appointment: Appointment,
    log: Any,
) -> None:
    """Delete every provider resource while preserving the local cancellation."""
    errors: list[str] = []
    attempted = False
    zoom_meeting_id = zoom_meeting_id_from_url(appointment.meeting_url)

    if zoom_meeting_id:
        attempted = True
        try:
            from app.services.zoom import delete_meeting

            await delete_meeting(meeting_id=zoom_meeting_id)
            log.info("zoom_meeting_deleted", appointment_id=appointment.id)
        except ZoomError:
            errors.append("Zoom meeting deletion failed")
            log.warning("zoom_meeting_delete_failed", appointment_id=appointment.id)
        except Exception:  # noqa: BLE001 - local cancellation must survive provider failure
            errors.append("Zoom meeting deletion failed")
            log.exception("zoom_meeting_delete_failed", appointment_id=appointment.id)

    if appointment.google_calendar_event_id:
        attempted = True
        if error := await delete_google_calendar_event(db, appointment=appointment, log=log):
            errors.append(error)

    if not attempted:
        return
    appointment.sync_status = "failed" if errors else "cancelled"
    appointment.sync_error = "; ".join(errors) if errors else None


async def delete_google_calendar_event(
    db: AsyncSession,
    *,
    appointment: Appointment,
    log: Any,
) -> str | None:
    """Delete only Google Calendar, preserving any Zoom meeting on reassignment."""
    if appointment.google_calendar_event_id is None:
        return None

    user_id = await _calendar_owner_user_id(db, appointment)
    if user_id is None:
        return "Assigned staff calendar is not connected"

    try:
        from app.services.google_calendar import delete_event

        await delete_event(
            db,
            user_id=user_id,
            event_id=appointment.google_calendar_event_id,
        )
        log.info("google_calendar_event_deleted", appointment_id=appointment.id)
    except GoogleCalendarError:
        log.warning("google_calendar_event_delete_failed", appointment_id=appointment.id)
        return "Google Calendar event deletion failed"
    except Exception:  # noqa: BLE001 - local reassignment must survive provider failure
        log.exception("google_calendar_event_delete_failed", appointment_id=appointment.id)
        return "Google Calendar event deletion failed"
    return None


async def _calendar_owner_user_id(db: AsyncSession, appointment: Appointment) -> int | None:
    if appointment.bookable_staff_id is None:
        return None
    loaded_staff = appointment.__dict__.get("bookable_staff")
    staff = (
        loaded_staff
        if isinstance(loaded_staff, BookableStaff)
        else await db.get(BookableStaff, appointment.bookable_staff_id)
    )
    return staff.user_id if staff is not None else None
