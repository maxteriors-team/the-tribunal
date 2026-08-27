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
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from openai.types.chat import ChatCompletionMessageToolCall
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.conversation_booking_draft import (
    BookingDraftCallType,
    ConversationBookingDraft,
)
from app.services.ai.base_tool_executor import BaseToolExecutor
from app.services.ai.booking_confirmation import is_explicit_booking_confirmation
from app.services.ai.contact_context_snapshot import ContactContextSnapshotService
from app.services.ai.contact_state_evidence import (
    ContactEvidenceDomain,
    build_contact_state_evidence,
    build_contact_state_not_found,
)
from app.services.ai.context_observability import observability_logger, observe_tool_call
from app.services.ai.website_lead_qualification import WebsiteLeadQualificationPolicy
from app.services.appointments.booking_finalizer import finalize_booking, format_contact_address
from app.services.appointments.booking_validation import validate_booking_request
from app.services.appointments.cancellation import cancel_upcoming_appointments
from app.services.approval.approval_gate_service import approval_gate_service
from app.services.leads.funnel_transitions import mark_contact_qualified
from app.utils.meeting_urls import meeting_provider_name

logger = structlog.get_logger()
_BOOKING_DRAFT_TTL = timedelta(hours=24)

# Read-only retrieval, reversible draft preparation, and explicit cancellation bypass
# the HITL approval gate. Calendar mutation still requires the gate.
GATE_EXEMPT_TOOLS: frozenset[str] = frozenset(
    {
        "search_knowledge",
        "lookup_contact_state",
        "prepare_booking",
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
                argument_keys=sorted(arguments),
            )
            observe_tool_call(
                observability_logger,
                surface="sms",
                invocation_id=str(self.conversation.id),
                tool_call_id=tool_call.id,
                tool_name=function_name,
                status="requested",
            )

            arguments, preflight_error = await self._preflight_tool_call(function_name, arguments)
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
                success = bool(result.get("success", False))
                self.log.info(
                    "tool_call_completed",
                    tool_call_id=tool_call.id,
                    success=success,
                )
                observe_tool_call(
                    observability_logger,
                    surface="sms",
                    invocation_id=str(self.conversation.id),
                    tool_call_id=tool_call.id,
                    tool_name=function_name,
                    status="completed" if success else "failed",
                    success=success,
                )
                continue

            result = await self._execute_gated_tool(function_name, arguments, preflight_error)

            results.append(
                {
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "content": json.dumps(result),
                }
            )

            success = bool(result.get("success", False))
            self.log.info(
                "tool_call_completed",
                tool_call_id=tool_call.id,
                success=success,
            )
            status: Literal["completed", "pending_approval", "blocked", "failed"] = "completed"
            if result.get("pending_approval"):
                status = "pending_approval"
            elif result.get("blocked"):
                status = "blocked"
            elif not success:
                status = "failed"
            observe_tool_call(
                observability_logger,
                surface="sms",
                invocation_id=str(self.conversation.id),
                tool_call_id=tool_call.id,
                tool_name=function_name,
                status=status,
                success=success,
            )

        return results

    async def _preflight_tool_call(
        self, function_name: str, arguments: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Replace untrusted booking arguments with the confirmed server draft."""
        if function_name != "book_appointment":
            return arguments, None
        draft_or_error = await self._confirmed_booking_draft(arguments)
        if isinstance(draft_or_error, dict):
            error = self._attach_fresh_evidence(
                draft_or_error,
                domains={"appointment", "availability"},
                has_evidence=False,
            )
            return arguments, error
        return self._booking_arguments_from_draft(draft_or_error, arguments), None

    async def _execute_gated_tool(
        self,
        function_name: str,
        arguments: dict[str, Any],
        preflight_error: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Apply the approval gate after tool-specific preflight validation."""
        if preflight_error is not None:
            return preflight_error
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
            return {
                "success": False,
                "pending_approval": True,
                "message": (
                    "I need approval from your operator for this action. They've been notified."
                ),
            }
        if decision == "blocked":
            return {
                "success": False,
                "blocked": True,
                "message": "I'm not permitted to perform this action.",
            }
        return await self.execute(function_name, arguments)

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

        if function_name in {"prepare_booking", "book_appointment", "check_availability"}:
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
        if function_name == "prepare_booking":
            return await self._execute_prepare_booking(arguments)
        if function_name == "book_appointment":
            return await self._execute_confirmed_booking(arguments)
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

    async def _execute_confirmed_booking(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Book only the persisted draft bound to the latest explicit confirmation."""
        draft_or_error = await self._confirmed_booking_draft(arguments)
        if isinstance(draft_or_error, dict):
            return self._attach_fresh_evidence(
                draft_or_error,
                domains={"appointment", "availability"},
                has_evidence=False,
            )
        draft = draft_or_error
        result = await self._execute_book_with_contact_lookup(
            date_str=draft.date.isoformat(),
            time_str=draft.time.strftime("%H:%M"),
            email=draft.email,
            customer_confirmed=True,
            duration_minutes=draft.duration_minutes,
            notes=arguments.get("notes"),
            required_skill=arguments.get("skill"),
            call_type=BookingDraftCallType(draft.call_type).value,
        )
        if result.get("success") is True:
            await self.db.delete(draft)
            await self.db.flush()
        return self._attach_fresh_evidence(
            result,
            domains={"appointment", "availability"},
            has_evidence=result.get("success") is True,
        )

    async def _confirmed_booking_draft(
        self, arguments: dict[str, Any]
    ) -> ConversationBookingDraft | dict[str, Any]:
        """Bind booking to the fresh summary immediately affirmed by the customer."""
        if arguments.get("customer_confirmed") is not True:
            return {
                "success": False,
                "blocked": True,
                "error": "explicit_confirmation_required",
                "message": "Please confirm the complete appointment summary first.",
            }

        draft_result = await self.db.execute(
            select(ConversationBookingDraft).where(
                ConversationBookingDraft.conversation_id == self.conversation.id,
                ConversationBookingDraft.workspace_id == self.conversation.workspace_id,
            )
        )
        draft = draft_result.scalar_one_or_none()
        if draft is None:
            return {
                "success": False,
                "blocked": True,
                "error": "booking_draft_missing",
                "message": "I need to restate the appointment details before booking.",
            }

        prepared_at = draft.prepared_at
        if prepared_at.tzinfo is None:
            prepared_at = prepared_at.replace(tzinfo=UTC)
        if draft.timezone != self.timezone or datetime.now(UTC) - prepared_at > _BOOKING_DRAFT_TTL:
            return {
                "success": False,
                "blocked": True,
                "error": "booking_draft_stale",
                "message": "That appointment summary expired. Which day should I recheck?",
            }

        recent_result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == self.conversation.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(2)
        )
        recent_messages = list(recent_result.scalars().all())
        if len(recent_messages) != 2:
            return {
                "success": False,
                "blocked": True,
                "error": "confirmation_context_missing",
                "message": "Please confirm the complete appointment summary first.",
            }
        latest, prior = recent_messages
        explicitly_affirmed = bool(
            latest.direction == MessageDirection.INBOUND
            and isinstance(latest.body, str)
            and is_explicit_booking_confirmation(latest.body)
        )
        summary_matches = bool(
            prior.direction == MessageDirection.OUTBOUND
            and isinstance(prior.body, str)
            and prior.body.strip() == draft.confirmation_text.strip()
        )
        if not explicitly_affirmed or not summary_matches:
            return {
                "success": False,
                "blocked": True,
                "error": "confirmation_context_mismatch",
                "message": "Please confirm the latest complete appointment summary first.",
            }
        return draft

    @staticmethod
    def _booking_arguments_from_draft(
        draft: ConversationBookingDraft,
        requested_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Replace model-supplied appointment fields with the confirmed server draft."""
        arguments: dict[str, Any] = {
            "date": draft.date.isoformat(),
            "time": draft.time.strftime("%H:%M"),
            "email": draft.email,
            "customer_confirmed": True,
            "duration_minutes": draft.duration_minutes,
            "call_type": BookingDraftCallType(draft.call_type).value,
            "booking_draft_prepared_at": draft.prepared_at.isoformat(),
        }
        notes = requested_arguments.get("notes")
        if isinstance(notes, str) and 0 < len(notes.strip()) <= 500:
            arguments["notes"] = notes.strip()
        skill = requested_arguments.get("skill")
        if isinstance(skill, str) and 0 < len(skill.strip()) <= 100:
            arguments["skill"] = skill.strip()
        return arguments

    async def _execute_prepare_booking(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Validate and atomically persist one complete confirmation draft."""
        contact = await self._get_contact()
        raw_email = arguments.get("email") or getattr(contact, "email", None)
        email = raw_email.strip() if isinstance(raw_email, str) else None
        raw_call_type = arguments.get("call_type")
        call_type = next(
            (
                member
                for member in BookingDraftCallType
                if isinstance(raw_call_type, str) and member.value == raw_call_type
            ),
            None,
        )
        if call_type is None:
            return {
                "success": False,
                "error": "invalid_call_type",
                "message": "Ask whether the customer prefers a phone call or video call.",
            }

        date_str = arguments.get("date", "")
        time_str = arguments.get("time", "")
        duration_minutes = arguments.get("duration_minutes", 30)
        validation = validate_booking_request(
            date_str=date_str,
            time_str=time_str,
            email=email,
            duration_minutes=duration_minutes,
            tz=self._get_timezone(),
            service_type=call_type.value,
        )
        if not validation.valid or validation.scheduled_at is None:
            return validation.as_tool_result()

        scheduled_at = validation.scheduled_at
        duration = int(duration_minutes)
        confirmation_text = self._booking_confirmation_text(
            scheduled_at=scheduled_at,
            timezone=self.timezone,
            duration_minutes=duration,
            call_type=call_type,
            email=email or "",
        )
        prepared_at = datetime.now(UTC)
        values = {
            "conversation_id": self.conversation.id,
            "workspace_id": self.conversation.workspace_id,
            "date": scheduled_at.date(),
            "time": scheduled_at.time().replace(tzinfo=None),
            "timezone": self.timezone,
            "duration_minutes": duration,
            "call_type": call_type,
            "email": email,
            "confirmation_text": confirmation_text,
            "prepared_at": prepared_at,
        }
        statement = (
            insert(ConversationBookingDraft)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[ConversationBookingDraft.conversation_id],
                set_={
                    key: value
                    for key, value in values.items()
                    if key not in {"conversation_id", "workspace_id"}
                },
                where=(ConversationBookingDraft.workspace_id == self.conversation.workspace_id),
            )
            .returning(ConversationBookingDraft.conversation_id)
        )
        persisted_id = (await self.db.execute(statement)).scalar_one_or_none()
        if persisted_id is None:
            self.log.warning("booking_draft_workspace_conflict")
            return {
                "success": False,
                "blocked": True,
                "error": "Booking draft scope does not match this conversation.",
            }

        return {
            "success": True,
            "booking_draft_prepared": True,
            "message": confirmation_text,
            "direct_response": confirmation_text,
        }

    @staticmethod
    def _booking_confirmation_text(
        *,
        scheduled_at: datetime,
        timezone: str,
        duration_minutes: int,
        call_type: BookingDraftCallType,
        email: str,
    ) -> str:
        """Return the exact summary the customer must affirm before booking."""
        date_text = scheduled_at.strftime("%A, %B %d, %Y").replace(" 0", " ")
        time_text = scheduled_at.strftime("%I:%M %p").lstrip("0")
        call_label = "phone call" if call_type is BookingDraftCallType.PHONE_CALL else "video call"
        return (
            f"Please confirm: {duration_minutes}-minute {call_label} on {date_text} at "
            f"{time_text} {timezone}, invitation to {email}. Is that correct?"
        )

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
        customer_confirmed: bool = False,
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
                customer_confirmed=customer_confirmed,
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
        if appointment and appointment.meeting_url:
            provider = meeting_provider_name(appointment.meeting_url)
            invite_copy = (
                f" A calendar invitation was sent to {email}."
                if appointment.sync_status == "synced"
                else ""
            )
            return (
                f"{call_label.title()} booked for {formatted_time}. "
                f"The {provider} link is {appointment.meeting_url}.{invite_copy}"
            )
        if appointment and appointment.sync_status == "synced":
            return (
                f"{call_label.title()} booked for {formatted_time}. "
                f"A calendar invitation was sent to {email}."
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
        """Create the Appointment and wait for provider metadata needed by this reply."""
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
            verify_availability=True,
            # The assistant's reply confirms the booking in this same SMS turn.
            # Suppress the generic lifecycle confirmation to avoid double-texting.
            send_customer_sms=False,
            # Provider sync must finish before formatting so video confirmations
            # include the real Zoom/Meet URL rather than promising an in-memory task.
            sync_external_events_before_return=True,
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
