"""Cal.com appointment state-machine handlers.

One async function per Cal.com webhook event (``BOOKING_CREATED``,
``BOOKING_RESCHEDULED``, ``BOOKING_CANCELLED``, ``MEETING_ENDED``). These
were extracted from the original monolithic ``calcom.py``; parsing helpers
live in :mod:`calcom_parser`, side-effect dispatch in :mod:`calcom_events`.
"""

from __future__ import annotations

import zoneinfo
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.api.webhooks.calcom_events import (
    build_confirmation_body,
    find_recent_voice_message,
    get_workspace_owner,
    resolve_campaign_id,
    send_lifecycle_sms,
)
from app.api.webhooks.calcom_parser import apply_contact_tag, find_contact_by_attendee
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.campaigns.guarantee_tracker import increment_completed_and_check_guarantee
from app.services.email import send_appointment_booked_notification
from app.services.push_notifications import push_notification_service
from app.utils.background_tasks import spawn_background_task


async def handle_booking_created(data: dict[str, Any], log: Any) -> None:  # noqa: PLR0912, PLR0915
    """Handle new Cal.com booking.

    Args:
        data: Cal.com booking data
        log: Logger instance
    """
    # Extract booking details
    booking_uid = data.get("uid", "")
    booking_id = data.get("id", "")
    event_type_id = data.get("eventTypeId", "")
    scheduled_at_str = data.get("startTime", "")
    duration_minutes = data.get("duration", 30)

    # Extract attendee info
    attendees = data.get("attendees", [])
    if not attendees:
        log.warning("no_attendees_in_booking")
        return

    attendee = attendees[0]
    email: str = attendee.get("email", "") or ""
    # Cal.com may supply the attendee phone as "phoneNumber" or "phone"
    attendee_phone: str | None = (
        attendee.get("phoneNumber") or attendee.get("phone") or None
    )

    log = log.bind(
        booking_uid=booking_uid,
        booking_id=booking_id,
        email=email,
        event_type_id=event_type_id,
    )
    log.info("processing_booking_created")

    # At least a booking UID and start time are required; email OR phone identifies contact
    if not all([booking_uid, scheduled_at_str]) or not (email or attendee_phone):
        log.warning("missing_required_fields")
        return

    try:
        scheduled_at = datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
    except Exception as e:
        log.warning("invalid_datetime_format", error=str(e))
        return

    async with AsyncSessionLocal() as db:
        # Look up contact by email with phone-number fallback
        contact = await find_contact_by_attendee(
            email=email or None,
            phone=attendee_phone,
            db=db,
            log=log,
        )

        if not contact:
            return

        # Apply lifecycle tag and status for scheduled appointment
        apply_contact_tag(contact, "appointment-scheduled")
        contact.last_appointment_status = "scheduled"
        db.add(contact)

        workspace_id = contact.workspace_id
        campaign_id_val = await resolve_campaign_id(db, contact.id, log)

        # Look up agent by event type ID if provided
        agent = None
        if event_type_id:
            agent_result = await db.execute(
                select(Agent).where(
                    Agent.workspace_id == workspace_id,
                    Agent.calcom_event_type_id == int(event_type_id),
                )
            )
            agent = agent_result.scalar_one_or_none()

        # Check if appointment already exists
        existing = await db.execute(
            select(Appointment).where(
                Appointment.calcom_booking_uid == booking_uid,
            )
        )
        appointment = existing.scalar_one_or_none()
        is_new_booking = appointment is None  # Track before upsert

        if appointment:
            # Update existing appointment
            log.info("updating_existing_appointment", appointment_id=appointment.id)
            appointment.scheduled_at = scheduled_at
            appointment.duration_minutes = duration_minutes
            appointment.calcom_booking_id = booking_id
            appointment.calcom_event_type_id = int(event_type_id) if event_type_id else None
            appointment.sync_status = "synced"
            appointment.last_synced_at = datetime.now(UTC)
            appointment.sync_error = None  # Clear any previous sync errors
        else:
            message_id = await find_recent_voice_message(
                db, contact.id, agent.id if agent else None, log,
            )

            # Create new appointment
            appointment = Appointment(
                workspace_id=workspace_id,
                contact_id=contact.id,
                agent_id=agent.id if agent else None,
                message_id=message_id,
                campaign_id=campaign_id_val,
                scheduled_at=scheduled_at,
                duration_minutes=duration_minutes,
                status="scheduled",
                calcom_booking_uid=booking_uid,
                calcom_booking_id=booking_id,
                calcom_event_type_id=int(event_type_id) if event_type_id else None,
                sync_status="synced",
                last_synced_at=datetime.now(UTC),
                sync_error=None,
            )
            db.add(appointment)

        await db.commit()
        await db.refresh(appointment)

        log.info(
            "booking_processed",
            appointment_id=appointment.id,
            sync_status="synced",
        )

        # Send confirmation SMS immediately for new bookings only.
        # Wrapped in send_lifecycle_sms which never raises — webhook always
        # returns 200 regardless of SMS outcome.
        if is_new_booking:
            # Fetch workspace to resolve timezone for time formatting
            ws_result = await db.execute(
                select(Workspace).where(Workspace.id == workspace_id)
            )
            workspace = ws_result.scalar_one_or_none()

            confirmation_body = build_confirmation_body(
                contact=contact,
                appointment=appointment,
                workspace=workspace,
                agent=agent,
            )
            log.info(
                "sending_booking_confirmation_sms",
                contact_id=contact.id,
                appointment_id=appointment.id,
            )
            await send_lifecycle_sms(
                db=db,
                workspace_id=workspace_id,
                contact=contact,
                agent=agent,
                body_text=confirmation_body,
            )

        # Email notification to realtor for new bookings
        if is_new_booking:
            try:
                owner = await get_workspace_owner(db, workspace_id)
                if owner:
                    realtor_email, realtor_name = owner
                    contact_name = (
                        " ".join(filter(None, [contact.first_name, contact.last_name]))
                        or "Unknown"
                    )
                    spawn_background_task(
                        send_appointment_booked_notification(
                            to_email=realtor_email,
                            realtor_name=realtor_name,
                            contact_name=contact_name,
                            contact_phone=contact.phone_number or "",
                            appointment_time=appointment.scheduled_at,
                        ),
                        name="appointment_booked_email:calcom_webhook",
                    )
                    log.info(
                        "appointment_booked_email_queued",
                        to_email=realtor_email,
                        contact_id=contact.id,
                    )
            except Exception:
                log.exception("appointment_booked_email_failed")

        # Push notification for new appointment
        try:
            contact_name = (
                " ".join(filter(None, [contact.first_name, contact.last_name]))
                or "Unknown"
            )
            await push_notification_service.send_to_workspace_members(
                db=db,
                workspace_id=str(workspace_id),
                title="New Appointment Booked",
                body=f"{contact_name} booked for {scheduled_at.strftime('%b %d at %I:%M %p')}",
                data={
                    "type": "appointment_booked",
                    "appointmentId": str(appointment.id),
                    "contactId": str(contact.id),
                    "screen": f"/(tabs)/appointments/{appointment.id}",
                },
                notification_type="message",
                channel_id="appointments",
            )
        except Exception:
            log.exception("appointment_push_notification_failed")

        # Double-booking detection — alert if contact has multiple scheduled appointments
        try:
            existing_scheduled = await db.execute(
                select(Appointment).where(
                    Appointment.contact_id == contact.id,
                    Appointment.status == "scheduled",
                    Appointment.id != appointment.id,
                ).order_by(Appointment.created_at.asc())
            )
            other_appointments = existing_scheduled.scalars().all()

            if other_appointments:
                parts = filter(None, [contact.first_name, contact.last_name])
                contact_name = " ".join(parts) or "Unknown"
                # The oldest existing appointment was booked first
                first_appt = other_appointments[0]
                first_time = first_appt.scheduled_at.strftime("%b %d at %I:%M %p")
                new_time = appointment.scheduled_at.strftime("%b %d at %I:%M %p")
                total = len(other_appointments) + 1
                body_msg = (
                    f"{contact_name} has {total} appointments. "
                    f"First: {first_time}, New: {new_time}"
                )

                await push_notification_service.send_to_workspace_members(
                    db=db,
                    workspace_id=str(workspace_id),
                    title="\u26a0\ufe0f Double Booking Detected",
                    body=body_msg,
                    data={
                        "type": "double_booking",
                        "contactId": str(contact.id),
                        "newAppointmentId": str(appointment.id),
                        "existingAppointmentId": str(first_appt.id),
                        "screen": f"/(tabs)/contacts/{contact.id}",
                    },
                    notification_type="message",
                    channel_id="appointments",
                )
                log.warning(
                    "double_booking_detected",
                    contact_id=contact.id,
                    contact_name=contact_name,
                    total_scheduled=len(other_appointments) + 1,
                    existing_appointment_ids=[a.id for a in other_appointments],
                    new_appointment_id=appointment.id,
                )
        except Exception:
            log.exception("double_booking_detection_failed")


async def handle_booking_rescheduled(data: dict[str, Any], log: Any) -> None:  # noqa: PLR0915
    """Handle Cal.com booking reschedule.

    Args:
        data: Cal.com booking data
        log: Logger instance
    """
    booking_uid = data.get("uid", "")
    scheduled_at_str = data.get("startTime", "")
    duration_minutes = data.get("duration", 30)

    log = log.bind(booking_uid=booking_uid)
    log.info("processing_booking_rescheduled")

    if not all([booking_uid, scheduled_at_str]):
        log.warning("missing_required_fields")
        return

    try:
        scheduled_at = datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
    except Exception as e:
        log.warning("invalid_datetime_format", error=str(e))
        return

    async with AsyncSessionLocal() as db:
        # Find appointment by booking UID
        result = await db.execute(
            select(Appointment).where(
                Appointment.calcom_booking_uid == booking_uid,
            )
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            log.warning("appointment_not_found")
            return

        # Update appointment
        appointment.scheduled_at = scheduled_at
        appointment.duration_minutes = duration_minutes
        appointment.sync_status = "synced"
        appointment.last_synced_at = datetime.now(UTC)

        # Reset reminder tracking so the reminder worker re-fires for the new time
        appointment.reminder_sent_at = None
        log.info(
            "reminder_tracking_reset_for_rescheduled_appointment",
            uid=booking_uid,
        )

        await db.commit()
        await db.refresh(appointment)

        log.info("booking_rescheduled", appointment_id=appointment.id)

        # Send rescheduled notification SMS — failures must not affect the webhook response
        try:
            contact_result = await db.execute(
                select(Contact).where(Contact.id == appointment.contact_id)
            )
            contact = contact_result.scalar_one_or_none()

            if contact:
                # Load agent (optional — used for from-number resolution)
                rescheduled_agent: Agent | None = None
                if appointment.agent_id:
                    agent_result = await db.execute(
                        select(Agent).where(Agent.id == appointment.agent_id)
                    )
                    rescheduled_agent = agent_result.scalar_one_or_none()

                # Load workspace for timezone formatting
                ws_result = await db.execute(
                    select(Workspace).where(Workspace.id == contact.workspace_id)
                )
                workspace = ws_result.scalar_one_or_none()

                # Format new date/time in workspace timezone
                tz_name = (
                    ((workspace.settings if workspace else None) or {}).get("timezone", "UTC")
                )
                try:
                    tz = zoneinfo.ZoneInfo(str(tz_name))
                except (KeyError, zoneinfo.ZoneInfoNotFoundError):
                    tz = zoneinfo.ZoneInfo("UTC")

                local_dt = appointment.scheduled_at.astimezone(tz)
                new_date = local_dt.strftime("%A, %B %-d")  # e.g. "Monday, March 24"
                new_time = local_dt.strftime("%-I:%M %p")   # e.g. "3:00 PM"

                first_name = contact.first_name or "there"
                rescheduled_body = (
                    f"Hi {first_name}, your appointment has been rescheduled to "
                    f"{new_date} at {new_time}. See you then! "
                    "Reply here if you need to make any changes."
                )

                log.info(
                    "sending_rescheduled_notification_sms",
                    contact_id=contact.id,
                    appointment_id=appointment.id,
                )
                await send_lifecycle_sms(
                    db=db,
                    workspace_id=contact.workspace_id,
                    contact=contact,
                    agent=rescheduled_agent,
                    body_text=rescheduled_body,
                )
        except Exception as e:
            log.warning("rescheduled_sms_setup_failed", error=str(e))

        # Push notification for rescheduled appointment
        try:
            contact_result_push = await db.execute(
                select(Contact).where(Contact.id == appointment.contact_id)
            )
            push_contact = contact_result_push.scalar_one_or_none()
            if push_contact:
                contact_name = (
                    " ".join(filter(None, [push_contact.first_name, push_contact.last_name]))
                    or "Unknown"
                )
                rescheduled_time = scheduled_at.strftime('%b %d at %I:%M %p')
                await push_notification_service.send_to_workspace_members(
                    db=db,
                    workspace_id=str(appointment.workspace_id),
                    title="Appointment Rescheduled",
                    body=f"{contact_name} rescheduled to {rescheduled_time}",
                    data={
                        "type": "appointment_rescheduled",
                        "appointmentId": str(appointment.id),
                        "contactId": str(push_contact.id),
                        "screen": f"/(tabs)/appointments/{appointment.id}",
                    },
                    notification_type="message",
                    channel_id="appointments",
                )
        except Exception:
            log.exception("reschedule_push_notification_failed")


async def handle_booking_cancelled(data: dict[str, Any], log: Any) -> None:  # noqa: PLR0912, PLR0915
    """Handle Cal.com booking cancellation.

    Args:
        data: Cal.com booking data
        log: Logger instance
    """
    booking_uid = data.get("uid", "")

    log = log.bind(booking_uid=booking_uid)
    log.info("processing_booking_cancelled")

    if not booking_uid:
        log.warning("missing_booking_uid")
        return

    # Determine if cancellation was host-initiated.
    # Cal.com sets `cancelledBy` to the email of the actor who cancelled.
    # If it matches the organizer email, the host cancelled — skip the rebook SMS.
    cancelled_by_email: str = (data.get("cancelledBy") or "").strip().lower()
    organizer_email: str = (data.get("organizer", {}).get("email") or "").strip().lower()
    is_host_initiated = bool(
        cancelled_by_email and organizer_email and cancelled_by_email == organizer_email
    )

    async with AsyncSessionLocal() as db:
        # Find appointment by booking UID
        result = await db.execute(
            select(Appointment).where(
                Appointment.calcom_booking_uid == booking_uid,
            )
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            log.warning("appointment_not_found")
            return

        # Update appointment status
        appointment.status = AppointmentStatus.CANCELLED
        appointment.sync_status = "synced"
        appointment.last_synced_at = datetime.now(UTC)
        appointment.sync_error = None  # Clear any previous sync errors

        # Update contact lifecycle fields for cancellation
        cancelled_contact_result = await db.execute(
            select(Contact).where(Contact.id == appointment.contact_id)
        )
        _cancelled_contact_pre = cancelled_contact_result.scalar_one_or_none()
        if _cancelled_contact_pre:
            apply_contact_tag(_cancelled_contact_pre, "appointment-cancelled")
            _cancelled_contact_pre.last_appointment_status = "cancelled"
            db.add(_cancelled_contact_pre)

        await db.commit()
        await db.refresh(appointment)

        log.info(
            "booking_cancelled",
            appointment_id=appointment.id,
            status=AppointmentStatus.CANCELLED,
            is_host_initiated=is_host_initiated,
        )

        # Send rebook SMS for attendee-initiated cancellations only.
        # Host-initiated cancellations are intentional — no rebook prompt needed.
        # Wrapped in try/except — never affects the webhook response.
        if not is_host_initiated:
            try:
                contact_result = await db.execute(
                    select(Contact).where(Contact.id == appointment.contact_id)
                )
                cancelled_contact = contact_result.scalar_one_or_none()

                if cancelled_contact:
                    # Load agent (used for rebook URL generation + from-number resolution)
                    cancelled_agent: Agent | None = None
                    if appointment.agent_id:
                        agent_result = await db.execute(
                            select(Agent).where(Agent.id == appointment.agent_id)
                        )
                        cancelled_agent = agent_result.scalar_one_or_none()

                    first_name = cancelled_contact.first_name or "there"

                    # Generate rebook URL if agent has a Cal.com event type configured
                    rebook_url: str | None = None
                    if (
                        cancelled_agent is not None
                        and cancelled_agent.calcom_event_type_id
                        and settings.calcom_api_key
                    ):
                        try:
                            from app.services.calendar.calcom import CalComService

                            calcom = CalComService(settings.calcom_api_key)
                            contact_name = " ".join(
                                filter(
                                    None,
                                    [cancelled_contact.first_name, cancelled_contact.last_name],
                                )
                            ) or first_name
                            rebook_url = calcom.generate_booking_url(
                                event_type_id=cancelled_agent.calcom_event_type_id,
                                contact_email=cancelled_contact.email or "",
                                contact_name=contact_name,
                                contact_phone=cancelled_contact.phone_number,
                            )
                        except Exception:
                            log.warning(
                                "cancellation_sms_rebook_url_failed",
                                appointment_id=appointment.id,
                            )

                    if rebook_url:
                        cancellation_body = (
                            f"Hi {first_name}, your appointment has been cancelled. "
                            f"We\u2019d love to find another time that works for you \u2014 "
                            f"book here: {rebook_url}. "
                            "Or reply to this message and we\u2019ll help you reschedule."
                        )
                    else:
                        cancellation_body = (
                            f"Hi {first_name}, your appointment has been cancelled. "
                            "We\u2019d love to find another time that works for you. "
                            "Reply to this message and we\u2019ll help you reschedule."
                        )

                    log.info(
                        "sending_cancellation_rebook_sms",
                        contact_id=cancelled_contact.id,
                        appointment_id=appointment.id,
                        has_rebook_url=rebook_url is not None,
                    )
                    await send_lifecycle_sms(
                        db=db,
                        workspace_id=cancelled_contact.workspace_id,
                        contact=cancelled_contact,
                        agent=cancelled_agent,
                        body_text=cancellation_body,
                    )
            except Exception as e:
                log.warning("cancellation_sms_setup_failed", error=str(e))

        # Push notification for cancelled appointment
        try:
            contact_result_push = await db.execute(
                select(Contact).where(Contact.id == appointment.contact_id)
            )
            push_contact = contact_result_push.scalar_one_or_none()
            if push_contact:
                contact_name = (
                    " ".join(filter(None, [push_contact.first_name, push_contact.last_name]))
                    or "Unknown"
                )
                cancelled_by = "by host" if is_host_initiated else "by client"
                await push_notification_service.send_to_workspace_members(
                    db=db,
                    workspace_id=str(appointment.workspace_id),
                    title="Appointment Cancelled",
                    body=f"{contact_name} cancelled {cancelled_by}",
                    data={
                        "type": "appointment_cancelled",
                        "appointmentId": str(appointment.id),
                        "contactId": str(push_contact.id),
                        "screen": f"/(tabs)/appointments/{appointment.id}",
                    },
                    notification_type="message",
                    channel_id="appointments",
                )
        except Exception:
            log.exception("cancellation_push_notification_failed")


async def handle_meeting_ended(data: dict[str, Any], log: Any) -> None:  # noqa: PLR0912, PLR0915
    """Handle Cal.com MEETING_ENDED event.

    Marks appointments as completed or no_show based on meeting data.
    """
    booking_uid = data.get("uid", "")

    log = log.bind(booking_uid=booking_uid)
    log.info("processing_meeting_ended")

    if not booking_uid:
        log.warning("missing_booking_uid")
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Appointment).where(
                Appointment.calcom_booking_uid == booking_uid,
            )
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            log.warning("appointment_not_found")
            return

        # Skip if already in terminal state
        if appointment.status in (
            AppointmentStatus.COMPLETED,
            AppointmentStatus.CANCELLED,
        ):
            log.info("appointment_already_terminal", status=appointment.status)
            return

        # Determine if completed or no-show
        no_show_host = data.get("noShowHost", False)
        attendees = data.get("attendees", [])

        if no_show_host or not attendees:
            appointment.status = AppointmentStatus.NO_SHOW
            log.info("appointment_no_show", appointment_id=appointment.id)
        else:
            appointment.status = AppointmentStatus.COMPLETED
            log.info("appointment_completed", appointment_id=appointment.id)

            # Update campaign guarantee tracking
            if appointment.campaign_id:
                await increment_completed_and_check_guarantee(
                    db, appointment.campaign_id, log
                )

        appointment.sync_status = "synced"
        appointment.last_synced_at = datetime.now(UTC)

        is_no_show = appointment.status == AppointmentStatus.NO_SHOW

        # Update contact lifecycle tags and status fields before committing
        meeting_contact_result = await db.execute(
            select(Contact).where(Contact.id == appointment.contact_id)
        )
        meeting_contact = meeting_contact_result.scalar_one_or_none()
        if meeting_contact:
            if is_no_show:
                apply_contact_tag(meeting_contact, "no-show")
                meeting_contact.last_appointment_status = "no_show"
                meeting_contact.noshow_count = (meeting_contact.noshow_count or 0) + 1
            else:
                apply_contact_tag(meeting_contact, "showed-up")
                meeting_contact.last_appointment_status = "completed"
            db.add(meeting_contact)

        await db.commit()

        log.info(
            "meeting_ended_processed",
            appointment_id=appointment.id,
            status=appointment.status,
        )

        # Send no-show re-engagement SMS with rebook link.
        # Wrapped in try/except — never affects the webhook response.
        if is_no_show:
            try:
                contact_result = await db.execute(
                    select(Contact).where(Contact.id == appointment.contact_id)
                )
                noshow_contact = contact_result.scalar_one_or_none()

                if noshow_contact:
                    # Load agent (used for noshow_sms_enabled flag + rebook URL)
                    noshow_agent: Agent | None = None
                    if appointment.agent_id:
                        agent_result = await db.execute(
                            select(Agent).where(Agent.id == appointment.agent_id)
                        )
                        noshow_agent = agent_result.scalar_one_or_none()

                    # Respect agent-level toggle (default True when no agent)
                    sms_enabled = (
                        noshow_agent.noshow_sms_enabled
                        if noshow_agent is not None
                        else True
                    )
                    if not sms_enabled:
                        log.info(
                            "noshow_sms_disabled_for_agent",
                            agent_id=str(appointment.agent_id),
                        )
                    else:
                        first_name = noshow_contact.first_name or "there"

                        # Generate rebook URL if possible
                        booking_url: str | None = None
                        if (
                            noshow_agent is not None
                            and noshow_agent.calcom_event_type_id
                            and settings.calcom_api_key
                        ):
                            try:
                                from app.services.calendar.calcom import CalComService

                                calcom = CalComService(settings.calcom_api_key)
                                contact_name = " ".join(
                                    filter(
                                        None,
                                        [noshow_contact.first_name, noshow_contact.last_name],
                                    )
                                ) or first_name
                                booking_url = calcom.generate_booking_url(
                                    event_type_id=noshow_agent.calcom_event_type_id,
                                    contact_email=noshow_contact.email or "",
                                    contact_name=contact_name,
                                    contact_phone=noshow_contact.phone_number,
                                )
                            except Exception:
                                log.warning(
                                    "noshow_sms_rebook_url_failed",
                                    appointment_id=appointment.id,
                                )

                        # Build the no-show SMS body.
                        # Use agent.noshow_template when set (supports {first_name}
                        # and {reschedule_link} placeholders); fall back to the
                        # built-in messages.
                        if noshow_agent is not None and noshow_agent.noshow_template:
                            noshow_body = noshow_agent.noshow_template.replace(
                                "{first_name}", first_name
                            ).replace(
                                "{reschedule_link}", booking_url or ""
                            )
                        elif booking_url:
                            noshow_body = (
                                f"Hi {first_name}, we missed you at your appointment today. "
                                f"No worries \u2014 would you like to find another time? "
                                f"Book here: {booking_url}"
                            )
                        else:
                            noshow_body = (
                                f"Hi {first_name}, we missed you at your appointment today. "
                                f"No worries \u2014 would you like to find another time? "
                                "Reply here to rebook."
                            )

                        log.info(
                            "sending_noshow_reengagement_sms",
                            contact_id=noshow_contact.id,
                            appointment_id=appointment.id,
                            has_rebook_url=booking_url is not None,
                        )
                        await send_lifecycle_sms(
                            db=db,
                            workspace_id=noshow_contact.workspace_id,
                            contact=noshow_contact,
                            agent=noshow_agent,
                            body_text=noshow_body,
                        )
            except Exception as e:
                log.warning("noshow_sms_setup_failed", error=str(e))

        # Send post-meeting SMS for completed (attended) appointments.
        # Only fires when agent.post_meeting_sms_enabled is True and a template
        # is configured. Wrapped in try/except — never affects webhook response.
        if not is_no_show:
            try:
                contact_result = await db.execute(
                    select(Contact).where(Contact.id == appointment.contact_id)
                )
                completed_contact = contact_result.scalar_one_or_none()

                if completed_contact:
                    # Load agent
                    completed_agent: Agent | None = None
                    if appointment.agent_id:
                        agent_result = await db.execute(
                            select(Agent).where(Agent.id == appointment.agent_id)
                        )
                        completed_agent = agent_result.scalar_one_or_none()

                    if (
                        completed_agent is not None
                        and completed_agent.post_meeting_sms_enabled
                        and completed_agent.post_meeting_template
                    ):
                        first_name = completed_contact.first_name or "there"
                        post_meeting_body = (
                            completed_agent.post_meeting_template.replace(
                                "{first_name}", first_name
                            )
                        )
                        log.info(
                            "sending_post_meeting_sms",
                            contact_id=completed_contact.id,
                            appointment_id=appointment.id,
                        )
                        await send_lifecycle_sms(
                            db=db,
                            workspace_id=completed_contact.workspace_id,
                            contact=completed_contact,
                            agent=completed_agent,
                            body_text=post_meeting_body,
                        )
            except Exception as e:
                log.warning("post_meeting_sms_setup_failed", error=str(e))
