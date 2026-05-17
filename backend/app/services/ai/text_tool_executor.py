"""Text agent tool execution service.

This module handles tool execution for text/SMS conversations, providing
Cal.com booking integration similar to VoiceToolExecutor but optimized
for the text channel's database-centric workflow.

Key differences from VoiceToolExecutor:
- Uses Conversation and AsyncSession for state management
- Creates Appointment records in database
- Updates Contact email when provided during booking

Usage:
    executor = TextToolExecutor(
        agent=agent,
        conversation=conversation,
        db=db,
        timezone="America/New_York",
    )
    result = await executor.execute("book_appointment", {"date": "2024-01-15", ...})
"""

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import structlog
from openai.types.chat import ChatCompletionMessageToolCall
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.user import User
from app.models.workspace import WorkspaceIntegration, WorkspaceMembership
from app.services.ai.base_tool_executor import BaseToolExecutor
from app.services.approval.approval_gate_service import approval_gate_service
from app.services.email import send_appointment_booked_notification
from app.utils.background_tasks import spawn_background_task

logger = structlog.get_logger()


class TextToolExecutor(BaseToolExecutor):
    """Executes tool calls for text/SMS conversations.

    Handles Cal.com booking operations with database persistence,
    contact email updates, and appointment record creation.

    Attributes:
        agent: Agent model with Cal.com configuration
        conversation: Conversation model for context
        db: Async database session
        timezone: Timezone for date handling
    """

    def __init__(
        self,
        agent: Agent,
        conversation: Conversation,
        db: AsyncSession,
        timezone: str = "America/New_York",
    ) -> None:
        super().__init__(agent=agent, timezone=timezone)
        self.conversation = conversation
        self.db = db
        self._contact: Contact | None = None
        self.log = logger.bind(
            service="text_tool_executor",
            agent_id=str(agent.id),
            conversation_id=str(conversation.id),
        )

    # ── OpenAI tool call handling ───────────────────────────────────

    async def handle_tool_calls(
        self,
        tool_calls: list[ChatCompletionMessageToolCall],
    ) -> list[dict[str, Any]]:
        """Handle tool calls from OpenAI and return results."""
        results = []

        for tool_call in tool_calls:
            function_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            self.log.info(
                "executing_tool_call",
                tool_call_id=tool_call.id,
                function_name=function_name,
                arguments=arguments,
            )

            # Check approval gate
            decision, _gate_result = await approval_gate_service.check_and_execute_or_queue(
                db=self.db,
                agent_id=self.agent.id,
                workspace_id=self.agent.workspace_id,
                action_type=function_name,
                action_payload=arguments,
                description=f"{function_name}: {arguments}",
                context={
                    "source": "text_conversation",
                    "conversation_id": str(self.conversation.id),
                },
            )

            if decision == "pending":
                result = {
                    "success": False,
                    "pending_approval": True,
                    "message": (
                        "I need approval from your operator for this action. They've been notified."
                    ),
                }
            elif decision == "blocked":
                result = {
                    "success": False,
                    "blocked": True,
                    "message": "I'm not permitted to perform this action.",
                }
            else:
                result = await self.execute(function_name, arguments)

            results.append(
                {
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "content": json.dumps(result),
                }
            )

            self.log.info(
                "tool_call_completed",
                tool_call_id=tool_call.id,
                success=result.get("success", False),
            )

        return results

    # ── Main dispatch ───────────────────────────────────────────────

    async def execute(
        self,
        function_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool call."""
        if function_name == "book_appointment":
            return await self._execute_book_with_contact_lookup(
                date_str=arguments.get("date", ""),
                time_str=arguments.get("time", ""),
                email=arguments.get("email"),
                duration_minutes=arguments.get("duration_minutes", 30),
                notes=arguments.get("notes"),
            )
        if function_name == "check_availability":
            try:
                return await self.execute_check_availability(
                    start_date_str=arguments.get("start_date", ""),
                    end_date_str=arguments.get("end_date"),
                )
            except Exception as e:
                self.log.exception("availability_check_failed", error=str(e))
                return {
                    "success": False,
                    "error": f"Failed to check availability: {e!s}",
                }

        self.log.warning("unknown_text_tool", function_name=function_name)
        return {"success": False, "error": f"Unknown function: {function_name}"}

    # ── Text-only booking wrapper ───────────────────────────────────

    async def _execute_book_with_contact_lookup(
        self,
        date_str: str,
        time_str: str,
        email: str | None = None,
        duration_minutes: int = 30,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Resolve contact, validate datetime, then delegate to base booking."""
        # Check config early (before contact lookup)
        error = self._validate_calcom_config()
        if error:
            return error

        # Get contact info
        contact = await self._get_contact()
        if not contact:
            return {
                "success": False,
                "error": "Contact not found for this conversation",
            }
        self._contact = contact

        # Use provided email or fall back to contact's existing email
        booking_email = email or contact.email

        # If email was provided and contact doesn't have one, update the contact
        if email and not contact.email:
            contact.email = email
            await self.db.flush()
            self.log.info("contact_email_updated", contact_id=contact.id, email=email)

        if not booking_email:
            self.log.info(
                "contact_email_missing_building_link",
                contact_id=contact.id,
                contact_name=contact.full_name,
            )
            return await self._build_booking_link(contact)

        # Parse date and time for the Appointment record
        try:
            tz = self._get_timezone()
            self._appointment_datetime = datetime.strptime(
                f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=tz)
        except ValueError as e:
            self.log.warning("invalid_datetime", error=str(e))
            return {
                "success": False,
                "error": f"Invalid date/time format: {e}",
            }

        # Store duration/notes for post_booking_success hook
        self._pending_duration = duration_minutes
        self._pending_notes = notes

        try:
            return await self.execute_book_appointment(
                date_str=date_str,
                time_str=time_str,
                email=booking_email,
                duration_minutes=duration_minutes,
                notes=notes,
            )
        except Exception as e:
            self.log.exception("booking_failed", error=str(e))
            return {
                "success": False,
                "error": f"Failed to create booking: {e!s}",
            }

    # ── Hook overrides ──────────────────────────────────────────────

    def get_contact_name(self) -> str:
        if self._contact:
            return self._contact.full_name or "Customer"
        return "Customer"

    def get_contact_phone(self) -> str | None:
        if self._contact:
            return self._clean_phone_number(self._contact.phone_number)
        return None

    def get_booking_metadata(self, notes: str | None) -> dict[str, Any] | None:
        return {
            "source": "ai_text_agent",
            "agent_id": str(self.agent.id),
            "conversation_id": str(self.conversation.id),
        }

    def format_availability_result(
        self,
        slots: list[Any],
        start_date_str: str,
        end_date_str: str | None,
    ) -> dict[str, Any]:
        """Format slots for text response with full weekday format."""
        self.log.info("availability_checked", slot_count=len(slots))

        formatted_slots = []
        for slot in slots:
            if slot.date and slot.time:
                try:
                    slot_dt = datetime.strptime(f"{slot.date} {slot.time}", "%Y-%m-%d %H:%M")
                    formatted = slot_dt.strftime("%A %b %d at %I:%M %p")
                    formatted_slots.append(formatted)
                except ValueError:
                    formatted_slots.append(f"{slot.date} {slot.time}")
            elif slot.time:
                formatted_slots.append(slot.time)

        if not formatted_slots and slots:
            self.log.warning(
                "slot_formatting_fallback",
                raw_slots=[{"date": s.date, "time": s.time} for s in slots[:5]],
            )
            formatted_slots = [f"{s.date} {s.time}" for s in slots[:10]]

        return {
            "success": True,
            "available_slots": formatted_slots,
            "slot_count": len(slots),
            "date_range": f"{start_date_str} to {end_date_str or start_date_str}",
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
        formatted_time = self._appointment_datetime.strftime("%A, %B %d at %I:%M %p")
        return {
            "success": True,
            "booking_uid": result.booking_uid,
            "scheduled_at": self._appointment_datetime.isoformat(),
            "duration_minutes": duration_minutes,
            "message": f"Appointment booked for {formatted_time}",
        }

    async def post_booking_success(
        self,
        result: Any,
        date_str: str,
        time_str: str,
        email: str,
        duration_minutes: int,
        notes: str | None,
    ) -> None:
        """Create Appointment record in database after successful booking."""
        self.log.info(
            "calcom_booking_created",
            booking_uid=result.booking_uid,
            booking_id=result.booking_id,
        )

        contact = self._contact
        assert contact is not None

        # Resolve campaign_id from conversation
        campaign_id_val = getattr(self.conversation, "campaign_id", None)

        appointment = Appointment(
            workspace_id=self.conversation.workspace_id,
            contact_id=contact.id,
            agent_id=self.agent.id,
            campaign_id=campaign_id_val,
            scheduled_at=self._appointment_datetime,
            duration_minutes=duration_minutes,
            status="scheduled",
            service_type="video_call",
            notes=notes,
            calcom_booking_uid=result.booking_uid,
            calcom_booking_id=result.booking_id,
            calcom_event_type_id=self.agent.calcom_event_type_id,
            sync_status="synced",
            last_synced_at=datetime.now(UTC),
        )
        self.db.add(appointment)
        await self.db.commit()
        await self.db.refresh(appointment)

        self.log.info("appointment_created", appointment_id=appointment.id)

        # Fire-and-forget email notification to the workspace owner/admin
        try:
            owner = await self._get_workspace_owner()
            if owner:
                realtor_email, realtor_name = owner
                spawn_background_task(
                    send_appointment_booked_notification(
                        to_email=realtor_email,
                        realtor_name=realtor_name,
                        contact_name=contact.full_name or "Unknown",
                        contact_phone=contact.phone_number or "",
                        appointment_time=appointment.scheduled_at,
                    ),
                    name="appointment_booked_email:text_tool_executor",
                )
                self.log.info(
                    "appointment_booked_email_queued",
                    to_email=realtor_email,
                    appointment_id=appointment.id,
                )
        except Exception:
            self.log.exception("appointment_booked_email_failed")

    # ── Text-only helpers ───────────────────────────────────────────

    async def _get_calcom_api_key(self) -> str | None:
        """Return the Cal.com API key for this workspace, or None if not found.

        Checks the workspace's WorkspaceIntegration record (type "calcom").
        Falls back to the global ``settings.calcom_api_key`` if set.
        """
        from app.core.config import settings
        from app.core.encryption import decrypt_json

        workspace_id = self.conversation.workspace_id
        result = await self.db.execute(
            select(WorkspaceIntegration).where(
                WorkspaceIntegration.workspace_id == workspace_id,
                WorkspaceIntegration.integration_type == "calcom",
                WorkspaceIntegration.is_active.is_(True),
            )
        )
        integration = result.scalar_one_or_none()
        if integration is not None:
            try:
                creds = decrypt_json(integration.encrypted_credentials)
                key = creds.get("api_key")
                if key:
                    return str(key)
            except Exception:
                self.log.warning("calcom_credential_decrypt_failed")

        # Fall back to global key
        global_key = settings.calcom_api_key
        return global_key if global_key else None

    async def _build_booking_link(self, contact: Contact) -> dict[str, Any]:
        """Build a Cal.com booking URL for a contact who has no email address.

        Fetches the Cal.com username via the v1 ``/me`` endpoint and the event
        slug via the v1 ``/event-types/{id}`` endpoint, then assembles a
        pre-filled booking URL and returns an action dict the AI should use to
        send the link via SMS.
        """
        username, slug, err = await self._resolve_calcom_identity()
        if err:
            return {"success": False, "error": err}

        # Build the pre-filled URL
        name_param = quote(contact.full_name or "", safe="")
        phone_param = quote(contact.phone_number or "", safe="")
        booking_url = f"https://cal.com/{username}/{slug}?name={name_param}&phone={phone_param}"

        self.log.info(
            "booking_link_built",
            contact_id=contact.id,
            booking_url=booking_url,
        )

        return {
            "success": True,
            "action": "send_booking_link",
            "booking_url": booking_url,
            "message": (
                f"I'd love to set something up! Here's my booking link where you can "
                f"pick a time that works for you: {booking_url}"
            ),
        }

    async def _resolve_calcom_identity(
        self,
    ) -> "tuple[str, str, None] | tuple[None, None, str]":
        """Fetch the Cal.com username and event slug for the current agent.

        Returns ``(username, slug, None)`` on success or
        ``(None, None, error_message)`` on failure.
        """
        event_type_id = self.agent.calcom_event_type_id
        if not event_type_id:
            return None, None, "Cal.com not configured for this agent"

        api_key = await self._get_calcom_api_key()
        if not api_key:
            return None, None, "Cal.com API key not available — cannot generate booking link"

        calcom_v1 = "https://api.cal.com/v1"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                username = await self._fetch_calcom_username(client, calcom_v1, api_key)
                if username is None:
                    return None, None, "Cal.com username not found — cannot generate booking link"

                slug = await self._fetch_event_slug(client, calcom_v1, api_key, event_type_id)
                if slug is None:
                    return None, None, "Cal.com event slug not found — cannot generate booking link"

        except httpx.HTTPError as exc:
            self.log.exception("calcom_booking_link_http_error", error=str(exc))
            return None, None, f"Network error building booking link: {exc!s}"

        return username, slug, None

    async def _fetch_calcom_username(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
    ) -> str | None:
        """Call Cal.com v1 /me and return the username, or None on failure."""
        resp = await client.get(f"{base_url}/me", params={"apiKey": api_key})
        if resp.status_code != 200:
            self.log.error("calcom_me_failed", status=resp.status_code, body=resp.text[:200])
            return None
        data = resp.json()
        return data.get("user", {}).get("username") or data.get("username") or None

    async def _fetch_event_slug(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        event_type_id: int,
    ) -> str | None:
        """Call Cal.com v1 /event-types/{id} and return the slug, or None on failure."""
        resp = await client.get(
            f"{base_url}/event-types/{event_type_id}",
            params={"apiKey": api_key},
        )
        if resp.status_code != 200:
            self.log.error(
                "calcom_event_type_failed",
                status=resp.status_code,
                event_type_id=event_type_id,
                body=resp.text[:200],
            )
            return None
        data = resp.json()
        event_type = data.get("event_type") or data.get("eventType") or data
        if not isinstance(event_type, dict):
            return None
        return event_type.get("slug") or None

    async def _get_workspace_owner(self) -> "tuple[str, str] | None":
        """Return (email, full_name) for the workspace owner or first admin/member."""
        workspace_id = self.conversation.workspace_id
        for role in ("owner", "admin", "member"):
            result = await self.db.execute(
                select(User.email, User.full_name)
                .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
                .where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.role == role,
                )
                .limit(1)
            )
            row = result.first()
            if row:
                email: str = row[0]
                full_name: str = row[1] or email.split("@")[0]
                return email, full_name
        return None

    async def _get_contact(self) -> Contact | None:
        """Get contact for this conversation."""
        if not self.conversation.contact_id:
            self.log.warning(
                "no_contact_id_on_conversation",
                conversation_phone=self.conversation.contact_phone,
            )
            return None

        result = await self.db.execute(
            select(Contact).where(Contact.id == self.conversation.contact_id)
        )
        contact = result.scalar_one_or_none()

        self.log.info(
            "contact_lookup",
            contact_id=self.conversation.contact_id,
            found=contact is not None,
        )
        return contact

    def _get_timezone(self) -> ZoneInfo:
        """Get ZoneInfo for configured timezone."""
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("America/New_York")

    def _clean_phone_number(self, phone: str | None) -> str | None:
        """Clean phone number to E.164 format for Cal.com."""
        if not phone:
            return None

        # Remove any non-digit chars except leading +
        cleaned = "".join(c for c in phone if c.isdigit())
        if not phone.startswith("+"):
            cleaned = "1" + cleaned if len(cleaned) == 10 else cleaned
        return "+" + cleaned
