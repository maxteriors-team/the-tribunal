"""Text agent tool execution service.

This module handles tool execution for text/SMS conversations, including CRM
booking and assigned-rep Google Calendar synchronization.

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
import re
from datetime import UTC, datetime
from typing import Any

import structlog
from openai.types.chat import ChatCompletionMessageToolCall
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.services.ai.base_tool_executor import BaseToolExecutor
from app.services.ai.contact_context_snapshot import ContactContextSnapshotService
from app.services.ai.contact_state_evidence import (
    ContactEvidenceDomain,
    build_contact_state_evidence,
    build_contact_state_not_found,
)
from app.services.ai.website_lead_qualification import WebsiteLeadQualificationPolicy
from app.services.appointments.booking_finalizer import finalize_booking, format_contact_address
from app.services.appointments.cancellation import cancel_upcoming_appointments
from app.services.approval.approval_gate_service import approval_gate_service
from app.services.leads.funnel_transitions import mark_contact_qualified

logger = structlog.get_logger()

# Read-only retrieval tools bypass the HITL approval gate. Cancellation is also exempt:
# delaying an explicit customer cancellation leaves reminders running after they opted out
# of the appointment.
GATE_EXEMPT_TOOLS: frozenset[str] = frozenset(
    {
        "search_knowledge",
        "lookup_contact_state",
        "cancel_appointment",
        "mark_lead_qualified",
    }
)


class TextToolExecutor(BaseToolExecutor):
    """Executes tool calls for text/SMS conversations.

    Handles Google Calendar booking operations with database persistence,
    contact email updates, and appointment record creation.

    Attributes:
        agent: Agent model with calendar configuration
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
        qualification_policy: WebsiteLeadQualificationPolicy | None = None,
    ) -> None:
        super().__init__(agent=agent, timezone=timezone)
        self.conversation = conversation
        self.db = db
        self._contact: Contact | None = None
        self.qualification_policy = qualification_policy
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

            scope_error = self._workspace_scope_error()
            if scope_error is not None:
                results.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "content": json.dumps(scope_error),
                    }
                )
                continue

            self.log.info(
                "executing_tool_call",
                tool_call_id=tool_call.id,
                function_name=function_name,
                arguments=(
                    {"redacted": True, "keys": sorted(arguments)}
                    if function_name == "mark_lead_qualified"
                    else arguments
                ),
            )

            # Read-only tools (e.g. knowledge lookups) skip the approval gate.
            if function_name in GATE_EXEMPT_TOOLS:
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
                continue

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

    async def execute(  # noqa: PLR0911
        self,
        function_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one workspace-bound SMS tool call."""
        scope_error = self._workspace_scope_error()
        if scope_error is not None:
            return scope_error

        if function_name in {"book_appointment", "check_availability"}:
            qualification_error = await self._qualification_booking_error()
            if qualification_error is not None:
                return qualification_error
        if function_name == "mark_lead_qualified":
            return await self._execute_mark_lead_qualified(arguments)
        if function_name == "lookup_contact_state":
            return await self._execute_lookup_contact_state(
                arguments.get("subject"),
                arguments.get("reference"),
            )
        if function_name == "book_appointment":
            result = await self._execute_book_with_contact_lookup(
                date_str=arguments.get("date", ""),
                time_str=arguments.get("time", ""),
                email=arguments.get("email"),
                duration_minutes=arguments.get("duration_minutes", 30),
                notes=arguments.get("notes"),
                required_skill=arguments.get("skill"),
                call_type=arguments.get("call_type"),
            )
            return self._attach_fresh_evidence(
                result,
                domains={"appointment", "availability"},
                has_evidence=result.get("success") is True,
            )
        if function_name == "check_availability":
            try:
                result = await self.execute_check_availability(
                    start_date_str=arguments.get("start_date", ""),
                    end_date_str=arguments.get("end_date"),
                    required_skill=arguments.get("skill"),
                    duration_minutes=arguments.get("duration_minutes", 30),
                )
            except Exception as exc:
                self.log.exception("availability_check_failed", error=str(exc))
                result = {
                    "success": False,
                    "error": f"Failed to check availability: {exc!s}",
                }
            return self._attach_fresh_evidence(
                result,
                domains={"availability"},
                has_evidence=result.get("available") is not False,
            )
        if function_name == "cancel_appointment":
            result = await self._execute_cancel_appointment(reason=arguments.get("reason"))
            return self._attach_fresh_evidence(
                result,
                domains={"appointment"},
                has_evidence=bool(result.get("cancelled_count")),
            )
        if function_name == "search_knowledge":
            result = await self._execute_search_knowledge(
                query=arguments.get("query", ""),
                top_k=arguments.get("top_k"),
            )
            return self._attach_fresh_evidence(
                result,
                domains={"pricing"},
                has_evidence=bool(result.get("results")),
            )

        self.log.warning("unknown_text_tool", function_name=function_name)
        return {"success": False, "error": f"Unknown function: {function_name}"}

    def _workspace_scope_error(self) -> dict[str, Any] | None:
        """Reject mismatched agent/conversation tenants before any query or action."""
        if self.agent.workspace_id == self.conversation.workspace_id:
            return None
        self.log.warning(
            "text_tool_workspace_scope_mismatch",
            agent_workspace_id=str(self.agent.workspace_id),
            conversation_workspace_id=str(self.conversation.workspace_id),
        )
        return {
            "success": False,
            "blocked": True,
            "error": "Tool scope does not match this conversation.",
            "evidence_status": "error",
        }

    @staticmethod
    def _attach_fresh_evidence(
        result: dict[str, Any],
        *,
        domains: set[str],
        has_evidence: bool,
    ) -> dict[str, Any]:
        """Mark whether this turn's tool result can support a factual claim."""
        enriched = dict(result)
        success = result.get("success") is True
        enriched.update(
            {
                "evidence_source": "live_tool",
                "observed_at": datetime.now(UTC).isoformat(),
                "evidence_domains": sorted(domains),
                "evidence_status": (
                    "found" if success and has_evidence else "absent" if success else "error"
                ),
            }
        )
        return enriched

    async def _execute_lookup_contact_state(
        self,
        subject: object,
        reference: object = None,
    ) -> dict[str, Any]:
        """Read a fresh, tenant-scoped CRM fact for this conversation's contact."""
        domain: ContactEvidenceDomain
        if subject == "quote":
            domain = "quote"
        elif subject == "invoice":
            domain = "invoice"
        elif subject == "appointment":
            domain = "appointment"
        else:
            return {
                "success": False,
                "error": "subject must be quote, invoice, or appointment",
                "evidence_status": "error",
            }

        contact_id = self.conversation.contact_id
        if contact_id is None:
            return build_contact_state_not_found(domains={domain})

        try:
            snapshot = await ContactContextSnapshotService(
                self.db,
                timeline_limit=10,
            ).get_snapshot(
                workspace_id=self.conversation.workspace_id,
                contact_id=contact_id,
            )
        except Exception as exc:
            self.log.exception(
                "lookup_contact_state_failed",
                contact_id=contact_id,
                subject=domain,
                error=str(exc),
            )
            return {
                "success": False,
                "error": (
                    "The live CRM record could not be verified. Hand off instead of "
                    "stating a quote, invoice, or appointment fact."
                ),
                "evidence_domains": [domain],
                "evidence_status": "error",
            }

        if snapshot is None:
            return build_contact_state_not_found(domains={domain})
        evidence = build_contact_state_evidence(
            snapshot,
            domains={domain},
            timezone=self.timezone,
        )
        return self._narrow_contact_state_evidence(
            evidence,
            domain=domain,
            reference=reference,
        )

    @staticmethod
    def _narrow_contact_state_evidence(
        evidence: dict[str, Any],
        *,
        domain: ContactEvidenceDomain,
        reference: object,
    ) -> dict[str, Any]:
        """Resolve one of several current records from the customer's exact wording."""
        if not isinstance(reference, str) or not reference.strip():
            return evidence

        ignored_tokens = {
            "a",
            "about",
            "appointment",
            "bill",
            "booking",
            "did",
            "estimate",
            "i",
            "invoice",
            "is",
            "me",
            "my",
            "proposal",
            "quote",
            "see",
            "the",
            "you",
        }
        reference_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", reference.casefold()[:200])
            if token not in ignored_tokens
        }
        if not reference_tokens:
            return evidence

        key = {
            "quote": "active_quotes",
            "invoice": "active_invoices",
            "appointment": "upcoming_appointments",
        }[domain]
        records = list(evidence.get(key) or [])
        latest_appointment = evidence.get("latest_appointment")
        if (
            domain == "appointment"
            and latest_appointment is not None
            and not any(
                record.get("appointment_id") == latest_appointment.get("appointment_id")
                for record in records
            )
        ):
            records.append(latest_appointment)

        scored_records = [
            (
                sum(
                    token in json.dumps(record, ensure_ascii=True).casefold()
                    for token in reference_tokens
                ),
                record,
            )
            for record in records
        ]
        best_score = max((score for score, _ in scored_records), default=0)
        matches = [
            record for score, record in scored_records if best_score > 0 and score == best_score
        ]
        status = "absent" if not matches else "found" if len(matches) == 1 else "conflict"

        narrowed = dict(evidence)
        narrowed["domain_status"] = {domain: status}
        narrowed["evidence_status"] = status
        if domain == "appointment":
            upcoming_ids = {
                record.get("appointment_id")
                for record in evidence.get("upcoming_appointments") or []
            }
            narrowed["upcoming_appointments"] = [
                record for record in matches if record.get("appointment_id") in upcoming_ids
            ]
            narrowed["latest_appointment"] = (
                latest_appointment if latest_appointment in matches else None
            )
        else:
            narrowed[key] = matches
        narrowed["message"] = (
            f"{evidence['message']} The customer's reference was matched only against "
            f"live {domain} fields; evidence_status={status}."
        )
        return narrowed

    async def _qualification_booking_error(self) -> dict[str, Any] | None:
        """Block direct booking calls until persisted website-lead qualification passes."""
        if self.qualification_policy is None:
            return None
        contact = await self._get_contact()
        if contact is not None and contact.is_qualified:
            return None
        return {
            "success": False,
            "blocked": True,
            "error": (
                "Booking and availability are unavailable until the website lead is "
                "persistently qualified. Continue the checklist one question at a time."
            ),
        }

    async def _execute_mark_lead_qualified(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Persist live website-lead qualification after strict local validation."""
        policy = self.qualification_policy
        contact = await self._get_contact()
        if policy is None or contact is None or contact.source != "lead_form":
            return {
                "success": False,
                "blocked": True,
                "error": "Qualification policy is not active for this website lead.",
            }

        score = arguments.get("score")
        evidence = arguments.get("criteria_evidence")
        summary = arguments.get("summary")
        if isinstance(score, bool) or not isinstance(score, int) or score < policy.min_score:
            return {
                "success": False,
                "error": f"Qualification score must be at least {policy.min_score}.",
            }
        if (
            not isinstance(evidence, list)
            or len(evidence) != len(policy.questions)
            or any(not isinstance(item, str) or not item.strip() for item in evidence)
        ):
            return {
                "success": False,
                "error": "Provide one non-empty evidence item for every qualification question.",
            }
        if not isinstance(summary, str) or not summary.strip():
            return {"success": False, "error": "Qualification summary is required."}

        if contact.status in {"converted", "lost"}:
            return {
                "success": False,
                "blocked": True,
                "error": f"Contact is terminal ({contact.status}); qualification was not changed.",
            }

        now = datetime.now(UTC)
        contact.lead_score = min(score, 100)
        contact.qualification_signals = {
            "source": "website_lead_live_ai",
            "score": min(score, 100),
            "criteria": [
                {"question": question, "evidence": str(item).strip()[:300]}
                for question, item in zip(policy.questions, evidence, strict=True)
            ],
            "summary": summary.strip()[:500],
            "last_analyzed_at": now.isoformat(),
        }
        opportunity = await mark_contact_qualified(self.db, contact)
        self._contact = contact
        self.log.info(
            "website_lead_qualified",
            contact_id=contact.id,
            score=min(score, 100),
            criteria_count=len(evidence),
        )
        return {
            "success": True,
            "qualified": True,
            "score": min(score, 100),
            "opportunity_id": str(opportunity.id) if opportunity is not None else None,
            "message": (
                f"Lead qualification persisted. Transition now to offering the "
                f"{policy.booking_label}; do not ask another qualification question."
            ),
        }

    # ── Knowledge retrieval ─────────────────────────────────────────

    async def _execute_search_knowledge(
        self,
        query: str,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """Retrieve on-demand knowledge passages for this conversation.

        Scoped to the conversation's workspace + the bound agent, reusing the
        conversation's existing DB session. Returns ranked passages tagged with
        their source document title for citation.
        """
        from app.services.knowledge.search_tool import execute_knowledge_search

        return await execute_knowledge_search(
            self.db,
            workspace_id=self.conversation.workspace_id,
            agent_id=self.agent.id,
            query=query,
            top_k=top_k,
        )

    # ── Text-only booking wrapper ───────────────────────────────────

    # ── Cancellation ────────────────────────────────────────────────

    async def _execute_cancel_appointment(
        self,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Cancel the contact's upcoming appointments.

        Returns a structured result the model turns into its reply. The
        ``nothing_to_cancel`` case is deliberately a success with a count of 0:
        the customer's instruction was honoured, there was simply nothing on the
        calendar, and reporting it as an error invites the model to apologise
        for a failure that did not happen.
        """
        contact = await self._get_contact()
        if not contact:
            return {
                "success": False,
                "error": "Contact not found for this conversation",
            }
        self._contact = contact

        try:
            result = await cancel_upcoming_appointments(
                self.db,
                workspace_id=self.agent.workspace_id,
                contact_id=contact.id,
                reason=reason,
                cancelled_by="customer",
            )
        except Exception as e:
            # Never let the model claim success off a failed cancellation —
            # that is the exact behaviour this tool was added to eliminate.
            self.log.exception("cancel_appointment_failed", contact_id=contact.id, error=str(e))
            return {
                "success": False,
                "error": (
                    "Could not cancel the appointment. Tell the customer you are "
                    "having trouble cancelling and a human will follow up — do not "
                    "tell them it is cancelled."
                ),
            }

        if result.count == 0:
            self.log.info("cancel_appointment_nothing_upcoming", contact_id=contact.id)
            return {
                "success": True,
                "cancelled_count": 0,
                "message": "No upcoming appointment was found for this customer.",
            }

        self.log.info(
            "cancel_appointment_succeeded",
            contact_id=contact.id,
            cancelled_count=result.count,
        )
        return {
            "success": True,
            "cancelled_count": result.count,
            "cancelled": [
                {"appointment_id": item.appointment_id, "when": item.local_label}
                for item in result.cancelled
            ],
            "message": (
                "Appointment cancelled. No further reminders will be sent. "
                "Confirm the cancellation to the customer."
            ),
        }

    # ── Booking ─────────────────────────────────────────────────────

    async def _execute_book_with_contact_lookup(
        self,
        date_str: str,
        time_str: str,
        email: str | None = None,
        duration_minutes: int = 30,
        notes: str | None = None,
        required_skill: str | None = None,
        call_type: str | None = None,
    ) -> dict[str, Any]:
        """Resolve contact, call type, and datetime, then delegate to base booking."""
        if call_type not in {"phone_call", "video_call"}:
            return {
                "success": False,
                "error": "Call type is required",
                "message": "Ask whether the lead prefers a phone call or video call.",
            }

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

        # Persist the email only after the appointment finalizer succeeds; a failed
        # slot/calendar attempt must not partially mutate the CRM contact.
        should_persist_email = bool(email and not contact.email)

        if not booking_email:
            return {
                "success": False,
                "error": "Email address is required for booking",
                "message": "Please ask the customer for their email address",
            }

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

        # Store selected call type for finalization and truthful response copy.
        self._pending_duration = duration_minutes
        self._pending_notes = notes
        self._pending_call_type = call_type

        try:
            result = await self.execute_book_appointment(
                date_str=date_str,
                time_str=time_str,
                email=booking_email,
                duration_minutes=duration_minutes,
                notes=notes,
                required_skill=required_skill,
                service_type=call_type,
            )
            if result.get("success") and should_persist_email and email:
                contact.email = email
                await self.db.flush()
                self.log.info("contact_email_updated", contact_id=contact.id)
            return result
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

    def get_contact_address(self) -> str | None:
        if self._contact:
            return format_contact_address(self._contact) or None
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
        call_type = getattr(self, "_pending_call_type", None)
        call_label = "video call" if call_type == "video_call" else "phone call"
        appointment = getattr(self, "_booked_appointment", None)
        return {
            "success": True,
            "scheduled_at": self._appointment_datetime.isoformat(),
            "duration_minutes": duration_minutes,
            "booking_email": email,
            "call_type": call_type,
            "invitation_sent": bool(appointment and appointment.sync_status == "synced"),
            "meeting_url": appointment.meeting_url if appointment else None,
            "message": self._booking_confirmation_message(call_label, formatted_time, email),
        }

    def _booking_confirmation_message(
        self, call_label: str, formatted_time: str, email: str
    ) -> str:
        appointment = getattr(self, "_booked_appointment", None)
        if appointment and appointment.sync_status == "synced":
            link_copy = (
                f" The Google Meet link is {appointment.meeting_url}."
                if appointment.meeting_url
                else ""
            )
            return (
                f"{call_label.title()} booked for {formatted_time}. "
                f"A calendar invitation was sent to {email}.{link_copy}"
            )
        return (
            f"{call_label.title()} is saved in the CRM for {formatted_time}, but the "
            "calendar invitation needs team follow-up. Do not promise a meeting link."
        )

    async def post_booking_success(
        self,
        result: Any,
        date_str: str,
        time_str: str,
        email: str,
        duration_minutes: int,
        notes: str | None,
    ) -> None:
        """Create the Appointment record and fire its downstream notifications."""
        self.log.info("booking_created")

        contact = self._contact
        assert contact is not None

        assigned_staff_id = self.assigned_staff_id()

        appointment = await finalize_booking(
            self.db,
            workspace_id=self.conversation.workspace_id,
            contact=contact,
            agent=self.agent,
            scheduled_at=self._appointment_datetime,
            duration_minutes=duration_minutes,
            campaign_id=getattr(self.conversation, "campaign_id", None),
            notes=notes,
            service_type=getattr(self, "_pending_call_type", "phone_call"),
            assigned_staff_id=assigned_staff_id,
            # The assistant's reply confirms the booking in this same SMS turn.
            # Suppress the generic lifecycle confirmation to avoid double-texting.
            send_customer_sms=False,
        )

        self._booked_appointment = appointment
        self.log.info("appointment_created", appointment_id=appointment.id)

    async def _get_contact(self) -> Contact | None:
        """Get contact for this conversation."""
        if not self.conversation.contact_id:
            self.log.warning(
                "no_contact_id_on_conversation",
                conversation_phone=self.conversation.contact_phone,
            )
            return None

        result = await self.db.execute(
            select(Contact).where(
                Contact.id == self.conversation.contact_id,
                Contact.workspace_id == self.conversation.workspace_id,
            )
        )
        contact = result.scalar_one_or_none()

        self.log.info(
            "contact_lookup",
            contact_id=self.conversation.contact_id,
            found=contact is not None,
        )
        return contact

    def _clean_phone_number(self, phone: str | None) -> str | None:
        """Clean phone number to E.164 format for calendar scheduling."""
        if not phone:
            return None

        # Remove any non-digit chars except leading +
        cleaned = "".join(c for c in phone if c.isdigit())
        if not phone.startswith("+"):
            cleaned = "1" + cleaned if len(cleaned) == 10 else cleaned
        return "+" + cleaned
