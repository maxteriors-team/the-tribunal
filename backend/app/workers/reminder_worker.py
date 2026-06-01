"""Appointment reminder worker.

Sends SMS reminders before scheduled appointments using the same phone number
the contact was originally reached on, ensuring a seamless conversation thread.

Supports multi-touch sequences: fires a separate SMS for each configured offset
in agent.reminder_offsets (e.g. 1440 min = 24 h, 120 min = 2 h, 30 min before)
and tracks which offsets have already fired in appointment.reminders_sent so
duplicate sends never occur across worker poll cycles.

Also supports a value-reinforcement pre-appointment message: a single SMS sent
``agent.value_reinforcement_offset_minutes`` minutes before the appointment.
The fired state is stored in ``appointment.reminders_sent`` using the sentinel
integer ``VR_SENTINEL`` (-1) so it is compatible with the existing
``ARRAY(Integer)`` column.
"""

import re
import zoneinfo
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.workspace import Workspace
from app.services.calendar.reminder_service import resolve_from_number
from app.services.idempotency import derive_outbound_key, derive_worker_retry_key
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.telnyx import TelnyxSMSService
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

MAX_REMINDERS_PER_TICK = 20

# Agentless appointments use this single offset (minutes before)
_AGENTLESS_DEFAULT_OFFSETS = [60]

# Sentinel stored in reminders_sent to indicate the value-reinforcement message
# has already been sent for an appointment.  Uses -1 because normal reminder
# offsets are always positive integers and the column is ARRAY(Integer).
VR_SENTINEL = -1


class ReminderWorker(RetryableWorker, BaseWorker):
    """Background worker for sending appointment reminders via SMS."""

    POLL_INTERVAL_SECONDS = 60
    COMPONENT_NAME = "reminder_worker"
    # SMS sends per appointment; modest cap so a backlog burst stays under
    # the per-number rate ceiling enforced downstream.
    MAX_CONCURRENCY = 5
    max_retries = 3
    backoff_base_seconds = 2.0

    def __init__(self) -> None:
        super().__init__()
        self.opt_out_manager = OptOutManager()

    async def _process_items(self) -> None:
        """Find and send due appointment reminders."""
        async with AsyncSessionLocal() as db:
            now = datetime.now(UTC)

            # Use a fixed 25-hour lookahead window — covers the largest
            # standard offset (1440 min = 24 h) with a safety margin.
            lookahead_minutes = 1500  # 25 hours

            # Broad fetch: scheduled appointments in the lookahead window
            # that still have at least one offset potentially unsent.
            # Precise per-offset filtering happens in Python after loading.
            result = await db.execute(
                select(Appointment)
                .options(
                    joinedload(Appointment.agent),
                    joinedload(Appointment.contact),
                    joinedload(Appointment.workspace),
                )
                .where(
                    and_(
                        Appointment.status == "scheduled",
                        Appointment.scheduled_at > now,
                        Appointment.scheduled_at <= now + timedelta(minutes=lookahead_minutes),
                        Appointment.contact_id.is_not(None),
                    )
                )
                .order_by(Appointment.scheduled_at)
                .limit(MAX_REMINDERS_PER_TICK)
            )
            appointments = result.unique().scalars().all()

            if not appointments:
                return

            # Build the list of (appointment, offset) pairs that are due
            due_pairs: list[tuple[Appointment, int]] = []
            for appt in appointments:
                agent = appt.agent
                if agent is not None and not agent.reminder_enabled:
                    continue

                offsets = (
                    agent.reminder_offsets
                    if agent is not None and agent.reminder_offsets
                    else _AGENTLESS_DEFAULT_OFFSETS
                )
                already_sent: list[int] = list(appt.reminders_sent or [])

                for offset in offsets:
                    if offset in already_sent:
                        continue  # Already fired this touchpoint
                    threshold = now + timedelta(minutes=offset)
                    if appt.scheduled_at <= threshold:
                        due_pairs.append((appt, offset))

            if due_pairs:
                self.logger.info(
                    "Processing appointment reminders",
                    count=len(due_pairs),
                )

                for appt, offset in due_pairs:
                    await self.execute_with_retry(
                        self._send_reminder,
                        appt,
                        offset,
                        db,
                        item_key=derive_worker_retry_key("reminder", appt.id, "offset", offset),
                    )

            # Value-reinforcement pre-appointment messages
            await self._process_value_reinforcement(appointments, now, db)

    async def _send_reminder(
        self,
        appt: Appointment,
        offset_minutes: int,
        db: AsyncSession,
    ) -> None:
        """Send a single appointment reminder SMS for the given offset."""
        log = self.logger.bind(appointment_id=appt.id, offset_minutes=offset_minutes)
        agent = appt.agent
        contact = appt.contact
        workspace = appt.workspace

        if contact is None or workspace is None:
            log.warning("Missing contact or workspace")
            return

        telnyx_key = settings.telnyx_api_key
        if not telnyx_key:
            log.warning("No Telnyx API key configured")
            return

        contact_phone = contact.phone_number
        if not contact_phone:
            log.warning("Contact has no phone number")
            return

        # TCPA compliance — skip opted-out contacts
        is_opted_out = await self.opt_out_manager.check_opt_out(
            workspace.id,
            contact_phone,
            db,
        )
        if is_opted_out:
            log.info(
                "Skipping reminder — contact has opted out",
                contact_id=contact.id,
                phone=contact_phone,
            )
            # Mark this offset as "sent" so we don't keep checking it every tick
            # for an opted-out contact.  The offset never fires, but it won't
            # silently retry on every poll cycle.
            await self._mark_offset_sent(appt, offset_minutes, db)
            return

        agent_id = agent.id if agent is not None else None

        # Resolve the from number
        from_number = await resolve_from_number(db, contact.id, workspace.id, agent_id)
        if not from_number:
            log.warning("Could not resolve from number, will retry next tick")
            return

        if agent is None:
            log.info(
                "Sending reminder for agentless (manually scheduled) appointment",
                contact_id=contact.id,
                from_number=from_number,
            )

        # Build SMS body
        body = self._render_reminder_body(
            template=agent.reminder_template if agent is not None else None,
            contact=contact,
            appointment=appt,
            workspace=workspace,
            agent=agent,
        )

        sms_service = TelnyxSMSService(telnyx_key)
        try:
            # Stable per-(appointment, offset) key so a worker crash between
            # the Message insert and the Telnyx POST is recoverable on the
            # next tick without sending the reminder twice.
            idempotency_key = derive_outbound_key("reminder", appt.id, offset_minutes)
            message = await sms_service.send_message(
                to_number=contact_phone,
                from_number=from_number,
                body=body,
                db=db,
                workspace_id=workspace.id,
                agent_id=agent_id,
                idempotency_key=idempotency_key,
            )

            log.info("Appointment reminder sent", message_id=str(message.id))

            # Mark this offset as fired and update legacy reminder_sent_at
            await self._mark_offset_sent(appt, offset_minutes, db)

            # If an agent owns this appointment, assign the conversation to them
            if agent is not None:
                conv_result = await db.execute(
                    select(Conversation)
                    .where(
                        and_(
                            Conversation.workspace_phone == from_number,
                            Conversation.contact_phone == contact_phone,
                            Conversation.workspace_id == workspace.id,
                        )
                    )
                    .order_by(Conversation.updated_at.desc())
                    .limit(1)
                )
                conversation = conv_result.scalars().first()
                if conversation:
                    conversation.assigned_agent_id = agent.id
                    conversation.ai_enabled = True

            await db.commit()

        except Exception as e:
            log.exception("Failed to send reminder SMS", error=str(e))
        finally:
            await sms_service.close()

    async def _process_value_reinforcement(
        self,
        appointments: Sequence[Appointment],
        now: datetime,
        db: AsyncSession,
    ) -> None:
        """Iterate over fetched appointments and fire any due VR messages.

        Extracted from ``_process_items`` to keep branch count below the
        ruff PLR0912 threshold.
        """
        for appt in appointments:
            agent = appt.agent
            if agent is None:
                continue
            if not agent.value_reinforcement_enabled:
                continue
            if not agent.value_reinforcement_template:
                continue

            already_sent: list[int] = list(appt.reminders_sent or [])
            if VR_SENTINEL in already_sent:
                continue  # Already sent the VR message for this appointment

            vr_offset = agent.value_reinforcement_offset_minutes
            threshold = now + timedelta(minutes=vr_offset)
            if appt.scheduled_at > threshold:
                continue  # Not within the VR send window yet

            await self.execute_with_retry(
                self._send_value_reinforcement,
                appt,
                db,
                item_key=derive_worker_retry_key("value_reinforcement", appt.id),
            )

    async def _send_value_reinforcement(
        self,
        appt: Appointment,
        db: AsyncSession,
    ) -> None:
        """Send the value-reinforcement pre-appointment SMS for an appointment.

        Uses the same opt-out check and 3-strategy from-number resolution as
        the standard reminder send path.  Tracks delivery via the VR_SENTINEL
        integer in ``appointment.reminders_sent``.
        """
        agent = appt.agent
        contact = appt.contact
        workspace = appt.workspace

        log = self.logger.bind(appointment_id=appt.id, message_type="value_reinforcement")

        if agent is None or contact is None or workspace is None:
            log.warning("Missing agent, contact, or workspace for VR message")
            return

        telnyx_key = settings.telnyx_api_key
        if not telnyx_key:
            log.warning("No Telnyx API key configured")
            return

        contact_phone = contact.phone_number
        if not contact_phone:
            log.warning("Contact has no phone number")
            return

        # TCPA compliance — skip opted-out contacts
        is_opted_out = await self.opt_out_manager.check_opt_out(
            workspace.id,
            contact_phone,
            db,
        )
        if is_opted_out:
            log.info(
                "Skipping value-reinforcement — contact has opted out",
                contact_id=contact.id,
                phone=contact_phone,
            )
            # Mark as sent so we don't keep checking on every poll cycle.
            await self._mark_offset_sent(appt, VR_SENTINEL, db)
            return

        # Resolve the from number using the same 3-strategy approach
        from_number = await resolve_from_number(db, contact.id, workspace.id, agent.id)
        if not from_number:
            log.warning("Could not resolve from number for VR message, will retry next tick")
            return

        # Render the template — value_reinforcement_template is non-None here
        # because _process_items checks it before calling this method.
        body = self._render_value_reinforcement_body(
            template=agent.value_reinforcement_template or "",
            contact=contact,
            appointment=appt,
            workspace=workspace,
        )

        sms_service = TelnyxSMSService(telnyx_key)
        try:
            # Stable per-appointment key (VR is single-shot per appointment).
            idempotency_key = derive_outbound_key("value_reinforcement", appt.id)
            message = await sms_service.send_message(
                to_number=contact_phone,
                from_number=from_number,
                body=body,
                db=db,
                workspace_id=workspace.id,
                agent_id=agent.id,
                idempotency_key=idempotency_key,
            )

            log.info("Value-reinforcement message sent", message_id=str(message.id))

            # Mark the VR message as sent using the sentinel value
            await self._mark_offset_sent(appt, VR_SENTINEL, db)

            await db.commit()

        except Exception as e:
            log.exception("Failed to send value-reinforcement SMS", error=str(e))
        finally:
            await sms_service.close()

    async def _mark_offset_sent(
        self,
        appt: Appointment,
        offset_minutes: int,
        db: AsyncSession,
    ) -> None:
        """Append offset_minutes to appointment.reminders_sent and update reminder_sent_at.

        Uses PostgreSQL array_append to avoid overwriting concurrent updates.
        After the append we refresh the ORM object so subsequent reads are
        accurate within the same session.

        The ``offset_minutes`` value may be ``VR_SENTINEL`` (-1) for the
        value-reinforcement message.
        """
        now = datetime.now(UTC)
        await db.execute(
            text(
                "UPDATE appointments "
                "SET reminders_sent = array_append(reminders_sent, :offset), "
                "    reminder_sent_at = :now "
                "WHERE id = :appt_id"
            ),
            {"offset": offset_minutes, "now": now, "appt_id": appt.id},
        )
        # Sync the in-memory object so the caller's view is consistent
        current = list(appt.reminders_sent or [])
        if offset_minutes not in current:
            current.append(offset_minutes)
        appt.reminders_sent = current
        appt.reminder_sent_at = now

    # ------------------------------------------------------------------
    # Template rendering
    # ------------------------------------------------------------------

    def _render_reminder_body(
        self,
        template: str | None,
        contact: Contact,
        appointment: Appointment,
        workspace: Workspace,
        agent: Agent | None,
    ) -> str:
        """Build the SMS body for a reminder.

        If agent.reminder_template is set, render it with placeholders:
          {first_name}, {last_name}, {appointment_date}, {appointment_time},
          {appointment_datetime}, {reschedule_link}

        Falls back to the original hardcoded message when no template is set.

        Times are formatted in the workspace timezone (falls back to UTC).
        """
        # Resolve timezone
        tz_name = (workspace.settings or {}).get("timezone", "UTC")
        try:
            tz = zoneinfo.ZoneInfo(str(tz_name))
        except (KeyError, zoneinfo.ZoneInfoNotFoundError):
            tz = zoneinfo.ZoneInfo("UTC")

        local_dt = appointment.scheduled_at.astimezone(tz)
        # e.g. "Monday, March 24"
        date_str = local_dt.strftime("%A, %B %-d")
        # e.g. "3:00 PM"
        time_str = local_dt.strftime("%-I:%M %p")
        datetime_str = f"{date_str} at {time_str}"

        first_name = contact.first_name or "there"

        # No custom template — return the original hardcoded message unchanged
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
                self.logger.warning(
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
                self.logger.warning(
                    "Placeholder replacement failed in reminder template",
                    placeholder=placeholder,
                    appointment_id=appointment.id,
                )

        return message

    def _render_value_reinforcement_body(
        self,
        template: str,
        contact: Contact,
        appointment: Appointment,
        workspace: Workspace,
    ) -> str:
        """Build the SMS body for a value-reinforcement message.

        Renders the template with placeholders:
          {first_name}, {appointment_date}, {appointment_time}

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

        replacements: dict[str, str] = {
            "first_name": contact.first_name or "",
            "appointment_date": date_str,
            "appointment_time": time_str,
        }

        message = template
        for placeholder, value in replacements.items():
            try:
                pattern = re.compile(rf"\{{{placeholder}\}}", re.IGNORECASE)
                message = pattern.sub(value, message)
            except Exception:
                self.logger.warning(
                    "Placeholder replacement failed in value-reinforcement template",
                    placeholder=placeholder,
                    appointment_id=appointment.id,
                )

        return message


# Singleton registry
_registry = WorkerRegistry(ReminderWorker)
start_reminder_worker = _registry.start
stop_reminder_worker = _registry.stop
get_reminder_worker = _registry.get
