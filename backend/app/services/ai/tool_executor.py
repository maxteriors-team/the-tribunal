"""Voice agent tool execution service.

This module extracts tool execution logic from voice_bridge.py into a
standalone, testable service. Handles execution of:
- check_availability: Query Cal.com for available slots
- book_appointment: Create appointment on Cal.com
- send_dtmf: Send touch-tone digits for IVR navigation
- send_application_link: Send the fixed Prestyj application URL by SMS

Usage:
    executor = VoiceToolExecutor(agent, contact_info, timezone)
    result = await executor.execute("check_availability", {"start_date": "2024-01-15"})
"""

import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from app.core.config import settings
from app.services.ai.base_tool_executor import BaseToolExecutor
from app.services.approval.approval_gate_service import approval_gate_service

logger = structlog.get_logger()

# Read-only tools that never mutate state and so bypass the HITL approval gate.
# Gating a knowledge lookup behind operator approval would stall the live call
# for a harmless retrieval, so it is always allowed to run.
# ``take_message`` is included: it only captures a structured message + notifies
# operators (no outbound action, no spend), and gating it behind approval would
# stall the live call and risk losing the message the caller is dictating.
GATE_EXEMPT_TOOLS: frozenset[str] = frozenset(
    {"search_knowledge", "lookup_caller_record", "take_message"}
)

_ALLOWED_MESSAGE_URGENCIES: frozenset[str] = frozenset({"low", "medium", "high"})

# Caps on how much of the caller's own record we read back into the live call.
# Bounded so a chatty record can't blow up latency or the prompt window.
MAX_LOOKUP_APPOINTMENTS = 5
MAX_LOOKUP_OPPORTUNITIES = 5
MAX_LOOKUP_NOTES_CHARS = 500

PRESTYJ_APPLICATION_URL = "https://prestyj.com/founding-cohort"
PRESTYJ_APPLICATION_SMS_BODY = (
    "Here is the Prestyj founding cohort application: "
    f"{PRESTYJ_APPLICATION_URL}\n\n"
    "Fill it out when you have a minute and Nolan will review it."
)


def _format_time_12h(time_24h: str) -> str:
    """Convert 24-hour HH:MM to 12-hour AM/PM (e.g. '14:00' -> '2:00 PM')."""
    try:
        dt = datetime.strptime(time_24h, "%H:%M")
        formatted = dt.strftime("%I:%M %p")
        if formatted.startswith("0"):
            formatted = formatted[1:]
        return formatted
    except ValueError:
        return time_24h


class VoiceToolExecutor(BaseToolExecutor):
    """Executes voice agent tool calls.

    Handles Cal.com booking operations, DTMF sending, and other
    tool calls from voice agents.

    Attributes:
        agent: Agent model with Cal.com configuration
        contact_info: Contact information for personalization
        timezone: Timezone for date handling
        call_control_id: Telnyx call control ID for DTMF
        log: Structured logger
    """

    max_slots = 10
    pre_validate = True

    def __init__(
        self,
        agent: Any,
        contact_info: dict[str, Any] | None = None,
        timezone: str = "America/New_York",
        call_control_id: str | None = None,
        workspace_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(agent=agent, timezone=timezone)
        self.contact_info = contact_info
        self.call_control_id = call_control_id
        self.workspace_id = workspace_id
        self.log = logger.bind(service="voice_tool_executor")

    # ── Main dispatch ───────────────────────────────────────────────

    async def execute(  # noqa: PLR0911 - flat tool dispatch table
        self,
        function_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool call."""
        self.log.info(
            "executing_voice_tool",
            function_name=function_name,
            arguments=arguments,
        )

        if function_name == "check_availability":
            return await self.execute_check_availability(
                start_date_str=arguments.get("start_date", ""),
                end_date_str=arguments.get("end_date"),
            )

        if function_name == "book_appointment":
            result = await self.execute_book_appointment(
                date_str=arguments.get("date", ""),
                time_str=arguments.get("time", ""),
                email=arguments.get("email"),
                duration_minutes=arguments.get("duration_minutes", 30),
                notes=arguments.get("notes"),
            )

            # Persist booking outcome to message record
            if self.call_control_id:
                outcome = "success" if result.get("success") else "failed"
                await self._persist_booking_outcome(outcome)

            return result

        if function_name == "send_dtmf":
            return await self._execute_send_dtmf(
                digits=arguments.get("digits", ""),
            )

        if function_name == "search_knowledge":
            return await self._execute_search_knowledge(
                query=arguments.get("query", ""),
                top_k=arguments.get("top_k"),
            )

        if function_name == "lookup_caller_record":
            return await self._execute_lookup_caller_record()

        if function_name == "take_message":
            return await self._execute_take_message(
                caller_name=arguments.get("caller_name"),
                callback_number=arguments.get("callback_number"),
                reason=arguments.get("reason"),
                urgency=arguments.get("urgency"),
                preferred_callback_time=arguments.get("preferred_callback_time"),
                message=arguments.get("message"),
            )

        if function_name == "send_application_link":
            return await self._execute_send_application_link()

        if function_name == "transfer_call":
            return await self._execute_transfer_call(
                reason=arguments.get("reason", ""),
                intent=arguments.get("intent"),
                summary=arguments.get("summary"),
            )

        self.log.warning("unknown_voice_tool", function_name=function_name)
        return {"success": False, "error": f"Unknown function: {function_name}"}

    # ── Hook overrides ──────────────────────────────────────────────

    def get_contact_name(self) -> str:
        if self.contact_info:
            name: str = self.contact_info.get("name", "Customer")
            return name
        return "Customer"

    def get_contact_phone(self) -> str | None:
        if self.contact_info:
            return self.contact_info.get("phone")
        return None

    def format_availability_result(
        self,
        slots: list[Any],
        start_date_str: str,
        end_date_str: str | None,
    ) -> dict[str, Any]:
        """Format slots for voice response with 12-hour display times."""
        slots_dicts = []
        for slot in slots:
            slots_dicts.append(
                {
                    "date": slot.date,
                    "time": slot.time,
                    "iso": slot.iso,
                    "display_time": _format_time_12h(slot.time),
                }
            )

        # Build voice-friendly message (limit to 5 for speaking)
        slot_descriptions = [s["display_time"] for s in slots_dicts[:5]]
        times_list = ", ".join(slot_descriptions)

        return {
            "success": True,
            "available": True,
            "slots": slots_dicts,
            "message": (
                f"Available times: {times_list}. "
                "IMPORTANT: ONLY offer these exact times to the customer. "
                "Do NOT make up or guess other available times."
            ),
        }

    def format_booking_success(
        self,
        result: Any,
        contact_name: str,
        date_str: str,
        time_str: str,
        email: str,
        duration_minutes: int,
    ) -> dict[str, Any]:
        display_time = _format_time_12h(time_str)
        return {
            "success": True,
            "booking_id": result.booking_uid,
            "booking_uid": result.booking_uid,
            "calcom_id": result.booking_id,
            "message": (
                f"Appointment booked for {contact_name} on {date_str} "
                f"at {display_time}. "
                f"Confirmation email sent to {email}."
            ),
        }

    def format_booking_failure(
        self,
        result: Any,
        time_str: str,
    ) -> dict[str, Any]:
        display_time = _format_time_12h(time_str)

        # Build alternative slots info for voice
        if result.alternative_slots:
            alt_slots = [
                {
                    "time": s.time,
                    "display_time": _format_time_12h(s.time),
                }
                for s in result.alternative_slots
            ]
            alt_times = ", ".join(s["display_time"] for s in alt_slots)
            return {
                "success": False,
                "error": (
                    f"The {display_time} slot is no longer available. "
                    "Do NOT re-offer this time to the customer."
                ),
                "alternative_slots": alt_slots,
                "message": (
                    f"That time is no longer available. "
                    f"{'Available alternatives: ' + alt_times + '. ' if alt_times else ''}"
                    "ONLY offer these exact alternative times. "
                    "Do NOT re-offer the failed time."
                ),
            }

        return {"success": False, "error": result.error or "Booking failed"}

    async def post_booking_success(
        self,
        result: Any,
        date_str: str,
        time_str: str,
        email: str,
        duration_minutes: int,
        notes: str | None,
    ) -> None:
        """Create Appointment record linked to the call's message."""
        if not self.call_control_id:
            return

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.db.session import AsyncSessionLocal
        from app.models.appointment import Appointment
        from app.models.conversation import Message as MessageModel

        async with AsyncSessionLocal() as db:
            try:
                msg_result = await db.execute(
                    select(MessageModel)
                    .options(selectinload(MessageModel.conversation))
                    .where(MessageModel.provider_message_id == self.call_control_id)
                )
                message = msg_result.scalar_one_or_none()
                if not message or not message.conversation:
                    self.log.warning(
                        "post_booking_no_message",
                        call_control_id=self.call_control_id,
                    )
                    return

                # Parse scheduled time
                try:
                    scheduled_at = datetime.strptime(
                        f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=UTC)
                except ValueError:
                    scheduled_at = datetime.now(UTC)

                # Resolve campaign_id from conversation
                campaign_id_val = getattr(message.conversation, "campaign_id", None)

                appointment = Appointment(
                    workspace_id=message.conversation.workspace_id,
                    contact_id=message.conversation.contact_id,
                    agent_id=message.agent_id,
                    message_id=message.id,
                    campaign_id=campaign_id_val,
                    scheduled_at=scheduled_at,
                    duration_minutes=duration_minutes,
                    status="scheduled",
                    calcom_booking_uid=result.booking_uid,
                    calcom_booking_id=result.booking_id,
                    sync_status="synced",
                    last_synced_at=datetime.now(UTC),
                    notes=notes,
                )
                db.add(appointment)
                await db.commit()
                self.log.info(
                    "appointment_created_from_voice",
                    appointment_message_id=str(message.id),
                    booking_uid=result.booking_uid,
                )
            except Exception as e:
                await db.rollback()
                self.log.error(
                    "post_booking_appointment_creation_failed",
                    error=str(e),
                    call_control_id=self.call_control_id,
                )

    # ── Voice-only tools ────────────────────────────────────────────

    async def _execute_send_application_link(self) -> dict[str, Any]:
        """Send the fixed Prestyj founding-cohort application URL to the current caller."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.db.session import AsyncSessionLocal
        from app.models.conversation import Message as MessageModel
        from app.services.idempotency import derive_outbound_key
        from app.services.telephony.text_provider import get_text_message_provider

        if not self.call_control_id:
            return {"success": False, "error": "No active call found for this SMS send."}

        async with AsyncSessionLocal() as db:
            msg_result = await db.execute(
                select(MessageModel)
                .options(selectinload(MessageModel.conversation))
                .where(MessageModel.provider_message_id == self.call_control_id)
            )
            call_message = msg_result.scalar_one_or_none()
            if not call_message or not call_message.conversation:
                self.log.warning(
                    "application_link_sms_no_call_message", call_control_id=self.call_control_id
                )
                return {"success": False, "error": "Could not find the current call conversation."}

            conversation = call_message.conversation
            workspace_id = self.workspace_id or conversation.workspace_id
            idempotency_key = derive_outbound_key(
                "voice_application_link_sms",
                call_message.id,
                PRESTYJ_APPLICATION_URL,
            )
            provider = get_text_message_provider("telnyx")
            try:
                sms_message = await provider.send_message(
                    to_number=conversation.contact_phone,
                    from_number=conversation.workspace_phone,
                    body=PRESTYJ_APPLICATION_SMS_BODY,
                    db=db,
                    workspace_id=workspace_id,
                    agent_id=call_message.agent_id,
                    campaign_id=call_message.campaign_id,
                    idempotency_key=idempotency_key,
                )
            finally:
                await provider.close()

        status = str(sms_message.status)
        if status == "failed":
            self.log.warning(
                "application_link_sms_failed",
                call_control_id=self.call_control_id,
                message_id=str(sms_message.id),
                error=getattr(sms_message, "error_message", None),
            )
            return {
                "success": False,
                "application_url": PRESTYJ_APPLICATION_URL,
                "error": getattr(sms_message, "error_message", None)
                or "SMS provider failed to send.",
            }

        self.log.info(
            "application_link_sms_sent",
            call_control_id=self.call_control_id,
            message_id=str(sms_message.id),
            status=status,
        )
        return {
            "success": True,
            "application_url": PRESTYJ_APPLICATION_URL,
            "message": "Application link sent by SMS.",
        }

    async def _execute_search_knowledge(
        self,
        query: str,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """Retrieve on-demand knowledge passages for the current call.

        Scoped to the call's workspace + agent (the call context): ``agent_id``
        comes from the bound agent and ``workspace_id`` from the executor (or the
        agent as a fallback). Returns ranked passages tagged with their source
        document title so the model can cite them out loud.
        """
        from app.db.session import AsyncSessionLocal
        from app.services.knowledge.search_tool import execute_knowledge_search

        agent_id = getattr(self.agent, "id", None)
        workspace_id = self.workspace_id or getattr(self.agent, "workspace_id", None)
        if agent_id is None or workspace_id is None:
            self.log.warning(
                "search_knowledge_missing_scope",
                has_agent_id=agent_id is not None,
                has_workspace_id=workspace_id is not None,
            )
            return {
                "success": False,
                "error": "Knowledge base is not available for this call.",
            }

        async with AsyncSessionLocal() as db:
            return await execute_knowledge_search(
                db,
                workspace_id=workspace_id,
                agent_id=agent_id,
                query=query,
                top_k=top_k,
            )

    async def _execute_lookup_caller_record(self) -> dict[str, Any]:
        """Read the CURRENT caller's own CRM record for account-specific answers.

        Strictly read-only. Every query is hard-scoped to BOTH the call's
        ``workspace_id`` AND the resolved ``contact_id``, so the receptionist can
        only ever read this one caller's record — never another contact's and
        never another workspace's. Unknown callers (no resolvable contact) get a
        safe ``found: False`` response so the model can gracefully say it has no
        record rather than inventing one.

        Returns the caller's upcoming appointments, open opportunities, contact
        status/notes, and a short last-interaction summary.
        """
        from sqlalchemy import or_, select
        from sqlalchemy.orm import selectinload

        from app.db.session import AsyncSessionLocal
        from app.models.appointment import Appointment, AppointmentStatus
        from app.models.contact import Contact
        from app.models.conversation import Message as MessageModel
        from app.models.opportunity import Opportunity, opportunity_contact_table

        not_found = {
            "success": True,
            "found": False,
            "message": (
                "No account record was found for this caller. Do NOT make up any "
                "appointment, status, or deal details — let them know you don't "
                "have a record on file and offer to take their information."
            ),
        }

        if not self.call_control_id:
            self.log.warning("lookup_caller_record_no_call_control_id")
            return not_found

        async with AsyncSessionLocal() as db:
            msg_result = await db.execute(
                select(MessageModel)
                .options(selectinload(MessageModel.conversation))
                .where(MessageModel.provider_message_id == self.call_control_id)
            )
            call_message = msg_result.scalar_one_or_none()
            if not call_message or not call_message.conversation:
                self.log.warning(
                    "lookup_caller_record_no_call_message",
                    call_control_id=self.call_control_id,
                )
                return not_found

            conversation = call_message.conversation
            # Workspace scope comes from the call itself, never from the model.
            workspace_id = self.workspace_id or conversation.workspace_id
            contact_id = conversation.contact_id
            if workspace_id is None or contact_id is None:
                return not_found

            # Load the contact scoped to BOTH workspace and id (defense in depth):
            # a contact row only matches if it belongs to this call's workspace.
            contact_result = await db.execute(
                select(Contact).where(
                    Contact.id == contact_id,
                    Contact.workspace_id == workspace_id,
                )
            )
            contact = contact_result.scalar_one_or_none()
            if contact is None:
                self.log.warning(
                    "lookup_caller_record_contact_not_in_workspace",
                    contact_id=str(contact_id),
                    workspace_id=str(workspace_id),
                )
                return not_found

            now = datetime.now(UTC)

            # Upcoming appointments: workspace + contact scoped, future + scheduled.
            appt_result = await db.execute(
                select(Appointment)
                .where(
                    Appointment.workspace_id == workspace_id,
                    Appointment.contact_id == contact_id,
                    Appointment.scheduled_at >= now,
                    Appointment.status == AppointmentStatus.SCHEDULED,
                )
                .order_by(Appointment.scheduled_at.asc())
                .limit(MAX_LOOKUP_APPOINTMENTS)
            )
            appointments = list(appt_result.scalars().all())

            # Open opportunities: workspace scoped, still open + active, and linked
            # to this caller either as primary contact or via the m2m table.
            opp_result = await db.execute(
                select(Opportunity)
                .outerjoin(
                    opportunity_contact_table,
                    opportunity_contact_table.c.opportunity_id == Opportunity.id,
                )
                .where(
                    Opportunity.workspace_id == workspace_id,
                    Opportunity.status == "open",
                    Opportunity.is_active.is_(True),
                    or_(
                        Opportunity.primary_contact_id == contact_id,
                        opportunity_contact_table.c.contact_id == contact_id,
                    ),
                )
                .order_by(Opportunity.created_at.desc())
                .distinct()
                .limit(MAX_LOOKUP_OPPORTUNITIES)
            )
            opportunities = list(opp_result.scalars().all())

            record = self._format_caller_record(
                contact=contact,
                appointments=appointments,
                opportunities=opportunities,
                conversation=conversation,
            )

        self.log.info(
            "lookup_caller_record_executed",
            call_control_id=self.call_control_id,
            contact_id=str(contact_id),
            workspace_id=str(workspace_id),
            appointment_count=len(record["upcoming_appointments"]),
            opportunity_count=len(record["open_opportunities"]),
        )
        return record

    def _format_caller_record(
        self,
        *,
        contact: Any,
        appointments: list[Any],
        opportunities: list[Any],
        conversation: Any,
    ) -> dict[str, Any]:
        """Shape a caller's own record into a safe, voice-friendly tool response."""
        try:
            tz = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo("America/New_York")

        appt_list = [
            {
                "when": appt.scheduled_at.astimezone(tz).strftime("%A, %B %d at %I:%M %p"),
                "iso": appt.scheduled_at.astimezone(tz).isoformat(),
                "duration_minutes": appt.duration_minutes,
                "status": str(appt.status),
                "service_type": appt.service_type,
            }
            for appt in appointments
        ]

        opp_list = [
            {
                "name": opp.name,
                "status": opp.status,
                "amount": float(opp.amount) if opp.amount is not None else None,
                "currency": opp.currency,
            }
            for opp in opportunities
        ]

        notes = contact.notes
        if notes and len(notes) > MAX_LOOKUP_NOTES_CHARS:
            notes = notes[:MAX_LOOKUP_NOTES_CHARS].rstrip() + "…"

        last_interaction: dict[str, Any] | None = None
        if conversation.last_message_at is not None:
            last_interaction = {
                "when": conversation.last_message_at.astimezone(tz).strftime(
                    "%A, %B %d at %I:%M %p"
                ),
                "direction": conversation.last_message_direction,
                "preview": conversation.last_message_preview,
                "channel": conversation.channel,
            }

        return {
            "success": True,
            "found": True,
            "contact": {
                "name": contact.full_name,
                "status": contact.status,
                "is_qualified": contact.is_qualified,
                "notes": notes,
            },
            "upcoming_appointments": appt_list,
            "open_opportunities": opp_list,
            "last_interaction": last_interaction,
            "message": (
                "This is the caller's own account record. Use ONLY these details "
                "to answer their account questions, and do not reveal information "
                "about anyone else."
            ),
        }

    async def _execute_take_message(
        self,
        *,
        caller_name: str | None,
        callback_number: str | None,
        reason: str | None,
        urgency: str | None,
        preferred_callback_time: str | None,
        message: str | None,
    ) -> dict[str, Any]:
        """Capture a structured "take a message" note and notify operators.

        Persists a :class:`PhoneMessage` linked to the current call's message +
        conversation/contact, then notifies workspace operators via push + email.
        Hard-scoped to the live call: workspace/contact/agent come from the call
        context, never from the model.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.db.session import AsyncSessionLocal
        from app.models.conversation import Message as MessageModel
        from app.models.phone_message import (
            PhoneMessage,
            PhoneMessageUrgency,
        )

        if not self.call_control_id:
            self.log.warning("take_message_no_call_control_id")
            return {
                "success": False,
                "error": "No active call found to attach this message to.",
            }

        normalized_urgency = (urgency or "").strip().lower()
        if normalized_urgency not in _ALLOWED_MESSAGE_URGENCIES:
            normalized_urgency = "medium"

        def _clip(value: str | None, limit: int) -> str | None:
            if value is None:
                return None
            text = value.strip()
            if not text:
                return None
            return text[:limit]

        caller_name = _clip(caller_name, 200)
        callback_number = _clip(callback_number, 32)
        reason = _clip(reason, 500)
        preferred_callback_time = _clip(preferred_callback_time, 200)
        message_body = message.strip() if message else None

        async with AsyncSessionLocal() as db:
            msg_result = await db.execute(
                select(MessageModel)
                .options(selectinload(MessageModel.conversation))
                .where(MessageModel.provider_message_id == self.call_control_id)
            )
            call_message = msg_result.scalar_one_or_none()
            if not call_message or not call_message.conversation:
                self.log.warning(
                    "take_message_no_call_message", call_control_id=self.call_control_id
                )
                return {
                    "success": False,
                    "error": "Could not find the current call to attach this message to.",
                }

            conversation = call_message.conversation
            workspace_id = self.workspace_id or conversation.workspace_id

            # Sensible fallbacks from the call context (never from the model).
            if not callback_number:
                callback_number = _clip(conversation.contact_phone, 32)
            if not caller_name:
                caller_name = _clip(self.get_contact_name(), 200)

            phone_message = PhoneMessage(
                workspace_id=workspace_id,
                message_id=call_message.id,
                conversation_id=conversation.id,
                contact_id=conversation.contact_id,
                agent_id=call_message.agent_id,
                caller_name=caller_name,
                callback_number=callback_number,
                reason=reason,
                urgency=PhoneMessageUrgency(normalized_urgency),
                preferred_callback_time=preferred_callback_time,
                message_body=message_body,
            )
            db.add(phone_message)
            await db.commit()
            await db.refresh(phone_message)

            phone_message_id = phone_message.id
            self.log.info(
                "take_message_captured",
                call_control_id=self.call_control_id,
                phone_message_id=str(phone_message_id),
                urgency=normalized_urgency,
            )

            await self._notify_message_operators(
                db,
                workspace_id=workspace_id,
                phone_message=phone_message,
            )

        return {
            "success": True,
            "message_id": str(phone_message_id),
            "message": (
                "Got it — I've taken the message and the team has been notified. "
                "Let the caller know their message has been passed along."
            ),
        }

    async def _notify_message_operators(
        self,
        db: Any,
        *,
        workspace_id: uuid.UUID,
        phone_message: Any,
    ) -> None:
        """Notify workspace operators of a newly taken message (push + email)."""
        from sqlalchemy import select

        from app.models.user import User
        from app.models.workspace import Workspace, WorkspaceMembership
        from app.services.email import send_taken_message_notification
        from app.services.idempotency import derive_outbound_key
        from app.services.push_notifications import push_notification_service

        workspace = await db.get(Workspace, workspace_id)
        workspace_name = workspace.name if workspace else "your workspace"

        who = phone_message.caller_name or phone_message.callback_number or "a caller"
        urgency = str(phone_message.urgency)
        summary = phone_message.reason or phone_message.message_body or "New message"
        title = f"New Message ({urgency})"
        body = f"{who}: {summary}"[:300]

        try:
            await push_notification_service.send_to_workspace_members(
                db=db,
                workspace_id=str(workspace_id),
                title=title,
                body=body,
                data={
                    "type": "message",
                    "phoneMessageId": str(phone_message.id),
                    "urgency": urgency,
                    "screen": (
                        f"/(tabs)/calls/{phone_message.message_id}"
                        if phone_message.message_id
                        else "/(tabs)/calls"
                    ),
                },
                notification_type="message",
                channel_id="calls",
            )
        except Exception as exc:
            self.log.exception("take_message_push_failed", error=str(exc))

        try:
            members = await db.execute(
                select(User)
                .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
                .where(WorkspaceMembership.workspace_id == workspace_id)
            )
            sent = 0
            for user in members.scalars().all():
                if not user.notification_email or not user.email:
                    continue
                idem = derive_outbound_key("take_message_email", phone_message.id, user.id)
                ok = await send_taken_message_notification(
                    to_email=user.email,
                    workspace_name=workspace_name,
                    caller_name=phone_message.caller_name,
                    callback_number=phone_message.callback_number,
                    reason=phone_message.reason,
                    urgency=urgency,
                    preferred_callback_time=phone_message.preferred_callback_time,
                    message_body=phone_message.message_body,
                    idempotency_key=idem,
                )
                sent += 1 if ok else 0
            self.log.info("take_message_email_dispatched", recipients=sent)
        except Exception as exc:
            self.log.exception("take_message_email_failed", error=str(exc))

    async def _execute_transfer_call(
        self,
        reason: str,
        intent: str | None,
        summary: str | None,
    ) -> dict[str, Any]:
        """Hand the active call to a human closer (warm or cold transfer).

        Resolves the destination + mode from agent/workspace config, then:
        - cold: issues the Telnyx ``transfer`` command (immediate bridge);
        - warm: dials a new leg to the closer, stashes pending state in Redis,
          and speaks a briefing \u2014 the voice webhook bridges on speak end.
        """
        from app.services.telephony.call_transfer import resolve_transfer_config
        from app.services.telephony.telnyx_voice import TelnyxVoiceService

        if not self.call_control_id or not settings.telnyx_api_key:
            return {
                "success": False,
                "error": "Telephony is not configured for transfers.",
            }

        ctx = await self._load_transfer_context()
        if ctx is None:
            return {"success": False, "error": "Could not find the current call."}

        resolution = resolve_transfer_config(self.agent, ctx["workspace_settings"])
        if resolution is None:
            return await self._reject_transfer_no_destination(ctx, reason, intent)

        log = self.log.bind(
            call_control_id=self.call_control_id,
            transfer_mode=resolution.mode,
        )
        voice_service = TelnyxVoiceService(settings.telnyx_api_key)
        try:
            if resolution.mode == "cold":
                return await self._do_cold_transfer(
                    voice_service, resolution, ctx, reason, intent, log
                )
            return await self._do_warm_transfer(
                voice_service, resolution, ctx, reason, intent, summary, log
            )
        except Exception as e:
            log.exception("transfer_call_error", error=str(e))
            return {"success": False, "error": f"Failed to transfer call: {e!s}"}
        finally:
            await voice_service.close()

    async def _load_transfer_context(self) -> dict[str, Any] | None:
        """Load workspace/contact/campaign context for the current call leg."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.db.session import AsyncSessionLocal
        from app.models.conversation import Message as MessageModel
        from app.models.workspace import Workspace

        async with AsyncSessionLocal() as db:
            msg_result = await db.execute(
                select(MessageModel)
                .options(selectinload(MessageModel.conversation))
                .where(MessageModel.provider_message_id == self.call_control_id)
            )
            call_message = msg_result.scalar_one_or_none()
            if not call_message or not call_message.conversation:
                self.log.warning("transfer_no_call_message", call_control_id=self.call_control_id)
                return None

            conversation = call_message.conversation
            workspace_id = self.workspace_id or conversation.workspace_id
            ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
            workspace = ws_result.scalar_one_or_none()

            return {
                "workspace_id": workspace_id,
                "workspace_settings": workspace.settings if workspace else None,
                "workspace_phone": conversation.workspace_phone,
                "contact_id": conversation.contact_id,
                "message_id": call_message.id,
                "campaign_id": call_message.campaign_id,
            }

    async def _reject_transfer_no_destination(
        self,
        ctx: dict[str, Any],
        reason: str,
        intent: str | None,
    ) -> dict[str, Any]:
        """Audit-log and return a friendly error when no destination is set."""
        from app.services.telephony.call_transfer import log_transfer_audit

        self.log.warning("transfer_no_destination_configured")
        await log_transfer_audit(
            workspace_id=ctx["workspace_id"],
            agent_id=getattr(self.agent, "id", None),
            message_id=ctx["message_id"],
            contact_id=ctx["contact_id"],
            campaign_id=ctx["campaign_id"],
            decision="blocked",
            reason="no_destination_configured",
            payload={"reason": reason, "intent": intent},
        )
        return {
            "success": False,
            "error": (
                "No human transfer destination is configured. "
                "Apologize and continue assisting the caller yourself."
            ),
        }

    async def _do_cold_transfer(
        self,
        voice_service: Any,
        resolution: Any,
        ctx: dict[str, Any],
        reason: str,
        intent: str | None,
        log: Any,
    ) -> dict[str, Any]:
        """Issue the native Telnyx transfer command and audit the outcome."""
        from app.services.telephony.call_transfer import log_transfer_audit

        assert self.call_control_id is not None
        ok = await voice_service.transfer_call(
            call_control_id=self.call_control_id,
            to_number=resolution.destination_number,
            from_number=ctx["workspace_phone"],
        )
        await log_transfer_audit(
            workspace_id=ctx["workspace_id"],
            agent_id=getattr(self.agent, "id", None),
            message_id=ctx["message_id"],
            contact_id=ctx["contact_id"],
            campaign_id=ctx["campaign_id"],
            decision="executed" if ok else "failed",
            reason=reason or "cold_transfer",
            payload={
                "mode": "cold",
                "destination": resolution.destination_number,
                "intent": intent,
            },
        )
        if not ok:
            return {
                "success": False,
                "error": "The transfer could not be started. Keep assisting the caller.",
            }
        log.info("cold_transfer_started")
        return {
            "success": True,
            "transferred": True,
            "mode": "cold",
            "message": (
                "Connecting the caller to a team member now. Let them know, then stop speaking."
            ),
        }

    async def _do_warm_transfer(
        self,
        voice_service: Any,
        resolution: Any,
        ctx: dict[str, Any],
        reason: str,
        intent: str | None,
        summary: str | None,
        log: Any,
    ) -> dict[str, Any]:
        """Dial the closer, stash pending state, and speak a briefing.

        The caller is bridged into the closer leg by the voice webhook handler
        once the spoken briefing finishes (``call.speak.ended``).
        """
        from app.services.telephony.call_transfer import (
            PendingTransfer,
            build_briefing,
            log_transfer_audit,
            make_transfer_leg_client_state,
            store_pending_transfer,
        )

        assert self.call_control_id is not None
        api_base = settings.api_base_url or "https://example.com"
        webhook_url = f"{api_base}/webhooks/telnyx/voice"
        connection_id = settings.telnyx_connection_id
        if not connection_id:
            connection_id = await voice_service.get_call_control_application_id(webhook_url)
        client_state = make_transfer_leg_client_state(self.call_control_id)
        closer_ccid = await voice_service.dial_transfer_leg(
            to_number=resolution.destination_number,
            from_number=ctx["workspace_phone"],
            connection_id=connection_id,
            webhook_url=webhook_url,
            client_state=client_state,
        )
        agent_id = getattr(self.agent, "id", None)
        if not closer_ccid:
            await log_transfer_audit(
                workspace_id=ctx["workspace_id"],
                agent_id=agent_id,
                message_id=ctx["message_id"],
                contact_id=ctx["contact_id"],
                campaign_id=ctx["campaign_id"],
                decision="failed",
                reason=reason or "warm_transfer",
                payload={
                    "mode": "warm",
                    "destination": resolution.destination_number,
                    "intent": intent,
                },
            )
            return {
                "success": False,
                "error": "Could not reach a team member right now. Keep assisting the caller.",
            }

        briefing = build_briefing(
            template=resolution.briefing_template,
            caller_name=self.get_contact_name(),
            intent=intent,
            summary=summary,
        )
        language = getattr(self.agent, "language", None) or "en-US"
        await store_pending_transfer(
            PendingTransfer(
                caller_call_control_id=self.call_control_id,
                closer_call_control_id=closer_ccid,
                workspace_id=str(ctx["workspace_id"]),
                agent_id=str(agent_id) if agent_id else None,
                mode="warm",
                briefing=briefing,
                language=language,
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        await log_transfer_audit(
            workspace_id=ctx["workspace_id"],
            agent_id=agent_id,
            message_id=ctx["message_id"],
            contact_id=ctx["contact_id"],
            campaign_id=ctx["campaign_id"],
            decision="executed",
            reason=reason or "warm_transfer",
            payload={
                "mode": "warm",
                "destination": resolution.destination_number,
                "closer_call_control_id": closer_ccid,
                "intent": intent,
                "briefing": briefing,
            },
        )
        log.info("warm_transfer_dialing", closer_call_control_id=closer_ccid)
        return {
            "success": True,
            "transferred": True,
            "mode": "warm",
            "message": (
                "Reaching a team member and briefing them now. "
                "Tell the caller you're connecting them, then stop speaking."
            ),
        }

    async def _execute_send_dtmf(self, digits: str) -> dict[str, Any]:
        """Execute send_dtmf tool for IVR navigation."""
        from app.services.telephony.telnyx_voice import TelnyxVoiceService

        # Validate inputs
        error_msg: str | None = None
        if not self.call_control_id:
            self.log.error("send_dtmf_no_call_control_id")
            error_msg = "No active call to send DTMF"
        elif not digits:
            error_msg = "No digits provided"
        elif not settings.telnyx_api_key:
            error_msg = "Telnyx API key not configured"
        else:
            # Validate digits
            valid_chars = set("0123456789*#ABCDabcdwW")
            invalid = [c for c in digits if c not in valid_chars]
            if invalid:
                error_msg = f"Invalid DTMF characters: {invalid}. Valid: 0-9, *, #, A-D, w, W"
            else:
                # Ensure at least one actual digit is present (not just pause chars)
                actual_digits = set("0123456789*#ABCDabcd")
                has_actual_digit = any(c in actual_digits for c in digits)
                if not has_actual_digit:
                    error_msg = (
                        "DTMF must include at least one digit (0-9, *, #, A-D). "
                        "You sent only pause characters. To navigate an IVR menu, "
                        "send the number for the option you want (e.g., '2' for sales)."
                    )

        if error_msg:
            return {"success": False, "error": error_msg}

        # At this point we know call_control_id is not None
        assert self.call_control_id is not None

        try:
            voice_service = TelnyxVoiceService(settings.telnyx_api_key)
            try:
                success = await voice_service.send_dtmf(
                    call_control_id=self.call_control_id,
                    digits=digits,
                )
            finally:
                await voice_service.close()

            if success:
                self.log.info(
                    "dtmf_sent_via_tool",
                    call_control_id=self.call_control_id,
                    digits=digits,
                )
                return {
                    "success": True,
                    "message": f"Sent DTMF tones: {digits}",
                    "digits": digits,
                }
            return {"success": False, "error": "Failed to send DTMF tones"}

        except Exception as e:
            self.log.exception("send_dtmf_error", error=str(e), digits=digits)
            return {"success": False, "error": f"Failed to send DTMF: {e!s}"}

    async def _persist_booking_outcome(self, outcome: str) -> None:
        """Persist booking outcome to message record."""
        if not self.call_control_id:
            return

        from sqlalchemy import update

        from app.db.session import AsyncSessionLocal
        from app.models.conversation import Message as MessageModel

        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    update(MessageModel)
                    .where(MessageModel.provider_message_id == self.call_control_id)
                    .values(booking_outcome=outcome)
                )
                await db.commit()
                self.log.info(
                    "booking_outcome_persisted",
                    call_control_id=self.call_control_id,
                    outcome=outcome,
                )
            except Exception as e:
                await db.rollback()
                self.log.error(
                    "booking_outcome_persistence_failed",
                    call_control_id=self.call_control_id,
                    outcome=outcome,
                    error=str(e),
                )


def create_tool_callback(
    agent: Any,
    contact_info: dict[str, Any] | None,
    timezone: str,
    call_control_id: str | None,
    log: Any,
    workspace_id: uuid.UUID | None = None,
) -> Any:
    """Create a tool callback function for voice sessions.

    This is a factory function that creates a callback closure
    capturing all the context needed for tool execution.

    Args:
        agent: Agent model with Cal.com config
        contact_info: Contact information
        timezone: Workspace timezone
        call_control_id: Telnyx call control ID
        log: Logger instance
        workspace_id: Workspace ID for outbound text attribution

    Returns:
        Async callback function for voice session tool calls
    """
    executor = VoiceToolExecutor(
        agent=agent,
        contact_info=contact_info,
        timezone=timezone,
        call_control_id=call_control_id,
        workspace_id=workspace_id,
    )

    async def tool_callback(
        call_id: str,
        function_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        log.info(
            "tool_callback_invoked",
            call_id=call_id,
            function_name=function_name,
            arguments=arguments,
        )

        # Read-only tools (e.g. knowledge lookups) skip the approval gate so a
        # live call never stalls waiting for operator sign-off on a retrieval.
        if function_name in GATE_EXEMPT_TOOLS:
            result = await executor.execute(function_name, arguments)
            log.info(
                "tool_callback_completed",
                call_id=call_id,
                function_name=function_name,
                result=result,
            )
            return result

        # Check approval gate (voice has no db session — gate opens its own)
        decision, gate_result = await approval_gate_service.check_and_execute_or_queue(
            db=None,
            agent_id=agent.id,
            workspace_id=agent.workspace_id,
            action_type=function_name,
            action_payload=arguments,
            description=f"{function_name}: {arguments}",
            context={"source": "voice_call", "call_id": call_id},
        )

        if decision == "pending":
            log.info(
                "action_pending_approval",
                function_name=function_name,
                gate_result=gate_result,
            )
            return {
                "success": False,
                "pending_approval": True,
                "message": (
                    "This action requires approval from your operator. "
                    "They've been notified and will respond shortly."
                ),
            }
        if decision == "blocked":
            log.info("action_blocked", function_name=function_name)
            return {
                "success": False,
                "blocked": True,
                "message": "This action is not permitted by your operator's policy.",
            }

        # decision == "auto" — proceed with normal execution
        result = await executor.execute(function_name, arguments)
        log.info(
            "tool_callback_completed",
            call_id=call_id,
            function_name=function_name,
            result=result,
        )
        return result

    return tool_callback
