"""Appointment reminder worker.

Sends reminders before scheduled appointments on the channels the agent is
configured for (``agent.reminder_channels``): SMS goes out on the same phone
number the contact was originally reached on, keeping one conversation thread,
and email goes to the contact's address.

Each channel tracks its own fired offsets (``reminders_sent`` for SMS,
``reminders_sent_email`` for email). Sharing one array would make an SMS send at
an offset silently suppress the email at the same offset.

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
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.encryption import hash_phone
from app.db.session import system_session
from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.workspace import Workspace
from app.services.calendar.reminder_service import resolve_from_number
from app.services.email import send_appointment_reminder_email
from app.services.idempotency import derive_outbound_key, derive_worker_retry_key
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.telnyx import TelnyxSMSService
from app.utils.meeting_urls import meeting_provider_name
from app.utils.timezones import resolve_workspace_timezone, workspace_timezone_name
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

MAX_REMINDERS_PER_TICK = 20

# Agentless appointments (manually scheduled, no agent to read settings from)
# fall back to this offset when the workspace has not configured its own.
_AGENTLESS_DEFAULT_OFFSETS = [60]

SMS_CHANNEL = "sms"
EMAIL_CHANNEL = "email"
DEFAULT_CHANNELS: tuple[str, ...] = (SMS_CHANNEL,)

# Per-channel dedupe columns. Kept as an explicit allowlist because the column
# name is interpolated into raw SQL below.
_SENT_COLUMN_BY_CHANNEL = {
    SMS_CHANNEL: "reminders_sent",
    EMAIL_CHANNEL: "reminders_sent_email",
}

# Sentinel stored in reminders_sent to indicate the value-reinforcement message
# has already been sent for an appointment.  Uses -1 because normal reminder
# offsets are always positive integers and the column is ARRAY(Integer).
VR_SENTINEL = -1


def _channels_for(agent: Agent | None) -> tuple[str, ...]:
    """Return the reminder channels configured for ``agent``.

    Unknown values are dropped rather than dispatched: a typo in the column must
    not become an unroutable send that retries forever.
    """
    configured = list(getattr(agent, "reminder_channels", None) or []) if agent is not None else []
    channels = tuple(c for c in configured if c in _SENT_COLUMN_BY_CHANNEL)
    return channels or DEFAULT_CHANNELS


def _agentless_offsets(workspace: Workspace | None) -> list[int]:
    """Return reminder offsets for an appointment with no agent.

    Manually scheduled appointments have no agent to read settings from, so the
    workspace can set its own default in
    ``settings["reminder_defaults"]["offsets"]``.
    """
    settings_blob = getattr(workspace, "settings", None) or {}
    defaults = settings_blob.get("reminder_defaults") if isinstance(settings_blob, dict) else None
    offsets = defaults.get("offsets") if isinstance(defaults, dict) else None
    if not isinstance(offsets, list):
        return _AGENTLESS_DEFAULT_OFFSETS
    valid = [int(o) for o in offsets if isinstance(o, int) and o > 0]
    return valid or _AGENTLESS_DEFAULT_OFFSETS


def _sent_offsets(appt: Appointment, channel: str) -> list[int]:
    """Return the offsets already fired for ``appt`` on ``channel``."""
    column = _SENT_COLUMN_BY_CHANNEL.get(channel, "reminders_sent")
    return list(getattr(appt, column, None) or [])


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
        async with system_session("reminder_worker sweeps every workspace") as db:
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

            due = self._collect_due_reminders(appointments, now)

            if due:
                self.logger.info("Processing appointment reminders", count=len(due))

                for appt, offset, channel in due:
                    sender = (
                        self._send_reminder_email
                        if channel == EMAIL_CHANNEL
                        else self._send_reminder
                    )
                    await self.execute_with_retry(
                        sender,
                        appt,
                        offset,
                        db,
                        item_key=derive_worker_retry_key(
                            "reminder", appt.id, f"{channel}_offset", offset
                        ),
                    )

            # Value-reinforcement pre-appointment messages
            await self._process_value_reinforcement(appointments, now, db)

    def _collect_due_reminders(
        self,
        appointments: Sequence[Appointment],
        now: datetime,
    ) -> list[tuple[Appointment, int, str]]:
        """Return the ``(appointment, offset, channel)`` triples that are due now."""
        due: list[tuple[Appointment, int, str]] = []
        for appt in appointments:
            agent = appt.agent
            if agent is not None and not agent.reminder_enabled:
                continue

            offsets = (
                agent.reminder_offsets
                if agent is not None and agent.reminder_offsets
                else _agentless_offsets(appt.workspace)
            )

            for channel in _channels_for(agent):
                already_sent = set(_sent_offsets(appt, channel))
                for offset in offsets:
                    if offset in already_sent:
                        continue  # Already fired this touchpoint on this channel
                    due_at = appt.scheduled_at - timedelta(minutes=offset)
                    if due_at < appt.created_at:
                        # The appointment was created inside this reminder window.
                        # Skip the stale touchpoint instead of sending a "reminder"
                        # seconds after the booking confirmation.
                        continue
                    if now >= due_at:
                        due.append((appt, offset, channel))
        return due

    async def _send_reminder_email(
        self,
        appt: Appointment,
        offset_minutes: int,
        db: AsyncSession,
    ) -> None:
        """Email a single appointment reminder for the given offset.

        Email is not covered by the SMS opt-out list (that is a TCPA control on
        texts), so the only gate here is having an address to send to.
        """
        log = self.logger.bind(
            appointment_id=appt.id,
            offset_minutes=offset_minutes,
            channel=EMAIL_CHANNEL,
        )
        contact = appt.contact
        workspace = appt.workspace
        if contact is None or workspace is None:
            log.warning("Missing contact or workspace")
            return

        if not contact.email:
            # Nothing will ever change within this appointment's window, so mark
            # it fired rather than re-evaluating it every 60s until the meeting.
            log.info("Skipping email reminder — contact has no email", contact_id=contact.id)
            await self._mark_offset_sent(appt, offset_minutes, db, channel=EMAIL_CHANNEL)
            await db.commit()
            return

        agent = appt.agent
        body = self._render_reminder_body(
            template=agent.reminder_template if agent is not None else None,
            contact=contact,
            appointment=appt,
            workspace=workspace,
            agent=agent,
        )

        sent = await send_appointment_reminder_email(
            to_email=contact.email,
            contact_name=contact.full_name or "there",
            business_name=workspace.name or "",
            body_text=body,
            appointment_time=appt.scheduled_at,
            timezone=workspace_timezone_name(workspace),
            idempotency_key=derive_outbound_key("reminder_email", appt.id, offset_minutes),
            anytime=appt.anytime,
        )
        if not sent:
            log.warning("Reminder email not accepted by provider, will retry next tick")
            return

        log.info("Appointment reminder email sent")
        await self._mark_offset_sent(appt, offset_minutes, db, channel=EMAIL_CHANNEL)
        await db.commit()

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
                            Conversation.workspace_phone_hash == hash_phone(from_number),
                            Conversation.contact_phone_hash == hash_phone(contact_phone),
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
        channel: str = SMS_CHANNEL,
    ) -> None:
        """Record that ``offset_minutes`` fired for ``appt`` on ``channel``.

        Uses PostgreSQL array_append to avoid overwriting concurrent updates.
        After the append we sync the ORM object so subsequent reads are accurate
        within the same session.

        The ``offset_minutes`` value may be ``VR_SENTINEL`` (-1) for the
        value-reinforcement message.
        """
        column = _SENT_COLUMN_BY_CHANNEL.get(channel, "reminders_sent")
        now = datetime.now(UTC)
        await db.execute(
            text(
                "UPDATE appointments "
                f"SET {column} = array_append({column}, :offset), "
                "    reminder_sent_at = :now "
                "WHERE id = :appt_id"
            ),
            {"offset": offset_minutes, "now": now, "appt_id": appt.id},
        )
        # Sync the in-memory object so the caller's view is consistent
        current = list(_sent_offsets(appt, channel))
        if offset_minutes not in current:
            current.append(offset_minutes)
        setattr(appt, column, current)
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
        """Build the shared SMS/email body for a reminder.

        If agent.reminder_template is set, render it with placeholders:
          {first_name}, {last_name}, {appointment_date}, {appointment_time},
          {appointment_datetime}, {reschedule_link}, {meeting_url}

        Video reminders always include either the real provider URL or truthful
        follow-up copy. Falls back to the original message when no template is set.

        Times are formatted in the workspace timezone — the zone the appointment
        was booked in, so a reminder cannot contradict the confirmation.
        """
        local_dt = appointment.scheduled_at.astimezone(resolve_workspace_timezone(workspace))
        # e.g. "Monday, March 24"
        date_str = local_dt.strftime("%A, %B %-d")
        time_str = "any time" if appointment.anytime else local_dt.strftime("%-I:%M %p")
        datetime_str = f"{date_str} at {time_str}"

        first_name = contact.first_name or "there"

        if not template:
            message = (
                f"Hi {first_name}, a quick reminder about your appointment "
                f"{datetime_str}. Reply here if you need to reschedule."
            )
        else:
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
                "meeting_url": appointment.meeting_url or "",
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

        return self._append_video_call_details(message, appointment)

    @staticmethod
    def _append_video_call_details(message: str, appointment: Appointment) -> str:
        """Append the provider-issued meeting URL once, never a fabricated link."""
        if appointment.service_type != "video_call":
            return message

        if appointment.meeting_url:
            if appointment.meeting_url in message:
                return message
            provider = meeting_provider_name(appointment.meeting_url)
            return f"{message}\nJoin {provider}: {appointment.meeting_url}"

        return f"{message}\nVideo-call link needs team follow-up. Reply here for help."

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

        Times are formatted in the workspace timezone — the zone the appointment
        was booked in, so a reminder cannot contradict the confirmation.
        """
        local_dt = appointment.scheduled_at.astimezone(resolve_workspace_timezone(workspace))
        date_str = local_dt.strftime("%A, %B %-d")
        time_str = "any time" if appointment.anytime else local_dt.strftime("%-I:%M %p")

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
