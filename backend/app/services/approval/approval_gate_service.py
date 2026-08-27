"""Central approval gate for the HITL (Human-In-The-Loop) system.

Decides whether an AI-proposed action should execute immediately,
be blocked, or be queued for human approval based on the agent's
HumanProfile policies.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.conversation_booking_draft import (
    BookingDraftCallType,
    ConversationBookingDraft,
)
from app.models.human_profile import HumanProfile
from app.models.pending_action import PendingAction
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/New_York"


def _zone_info(timezone: str) -> ZoneInfo:
    """Return ZoneInfo for ``timezone``, falling back to the default zone."""
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


class ApprovalActionExecutionError(RuntimeError):
    """Raised when an approved action handler fails and should be retried."""

    def __init__(self, action_id: uuid.UUID, action_type: str) -> None:
        self.action_id = action_id
        self.action_type = action_type
        super().__init__(f"Failed to execute approved action {action_id} ({action_type})")


class ApprovedActionHandler(Protocol):
    """Typed handler contract for executing one pending-action command type."""

    @property
    def action_type(self) -> str:
        """PendingAction.action_type handled by this command handler."""
        ...

    async def execute(self, db: AsyncSession, action: PendingAction) -> dict[str, Any]:
        """Execute the approved pending action and return a JSON-serializable result."""
        ...


@dataclass(slots=True, frozen=True)
class OutboundFollowUpCampaignSuggestionHandler:
    """Acknowledge an approved outbound follow-up campaign suggestion."""

    action_type: str = "outbound_improvement.follow_up_campaign"

    async def execute(self, db: AsyncSession, action: PendingAction) -> dict[str, Any]:
        return {
            "status": "acknowledged",
            "recommendation": action.action_payload.get("recommended_campaign", {}),
            "source": action.context.get("source"),
            "dedupe_key": action.context.get("dedupe_key"),
        }


@dataclass(slots=True, frozen=True)
class DealCoachFollowUpActionHandler:
    """Acknowledge an approved Deal Coach drafted follow-up action.

    The Deal Coach drafts a next-best action (e.g. a re-engagement SMS or a
    book-a-call nudge) and queues it for human approval. Approval records the
    operator's intent; actual outbound delivery is handled by the operator's
    normal send path, so execution here just acknowledges the decision.
    """

    action_type: str = "deal_coach.follow_up"

    async def execute(self, db: AsyncSession, action: PendingAction) -> dict[str, Any]:
        payload = action.action_payload
        return {
            "status": "acknowledged",
            "channel": payload.get("channel"),
            "opportunity_id": action.context.get("opportunity_id"),
            "contact_id": action.context.get("contact_id"),
            "source": action.context.get("source"),
        }


@dataclass(slots=True, frozen=True)
class LaunchCampaignHandler:
    """Start an auto-drafted outbound campaign once a human approves it.

    The auto-draft worker parks a draft campaign behind an
    ``outbound.launch_campaign`` PendingAction; approval flips the draft to
    running via the shared campaign lifecycle (same path as the campaigns
    API), so every send still passes the human gate.
    """

    action_type: str = "outbound.launch_campaign"

    async def execute(self, db: AsyncSession, action: PendingAction) -> dict[str, Any]:
        from app.services.campaigns.campaign_lifecycle import (
            CampaignLifecycleError,
            get_campaign_for_workspace,
            start_campaign,
        )

        raw_campaign_id = action.action_payload.get("campaign_id")
        try:
            campaign_id = uuid.UUID(str(raw_campaign_id))
        except (TypeError, ValueError):
            return {"error": "invalid_campaign_id", "campaign_id": raw_campaign_id}

        campaign = await get_campaign_for_workspace(db, campaign_id, action.workspace_id)
        if campaign is None:
            return {"error": "campaign_not_found", "campaign_id": str(campaign_id)}

        try:
            result = await start_campaign(db, campaign)
        except CampaignLifecycleError as exc:
            return {
                "error": "campaign_not_startable",
                "campaign_id": str(campaign_id),
                "detail": str(exc),
            }

        return {
            "status": "started",
            "campaign_id": str(campaign_id),
            "campaign_status": result.status.value,
            "contact_count": result.contact_count,
        }


@dataclass(slots=True, frozen=True)
class BookAppointmentActionHandler:
    """Execute a book_appointment pending action and persist the appointment.

    ``BookingService`` validates the local slot while ``finalize_booking`` writes
    the CRM row and mirrors it to the assigned Google Calendar. The live
    tool executors write that row in their ``post_booking_success`` hook, which
    the approval path never runs, so this handler must write it too. Without it
    an approved booking reports success and appears on no calendar.
    """

    action_type: str = "book_appointment"

    async def execute(self, db: AsyncSession, action: PendingAction) -> dict[str, Any]:
        from app.services.appointments.booking_finalizer import finalize_booking, load_agent
        from app.services.calendar.booking import BookingService

        payload = dict(action.action_payload)
        draft_or_error = await self._validated_text_booking_draft(db, action, payload)
        if isinstance(draft_or_error, dict):
            return draft_or_error
        draft = draft_or_error
        if draft is not None:
            payload.update(
                {
                    "date": draft.date.isoformat(),
                    "time": draft.time.strftime("%H:%M"),
                    "email": draft.email,
                    "duration_minutes": draft.duration_minutes,
                    "call_type": BookingDraftCallType(draft.call_type).value,
                }
            )

        contact = await self._resolve_contact(db, action)
        if contact is None:
            logger.error(
                "book_appointment action %s has no resolvable contact (context=%s)",
                action.id,
                action.context,
            )
            return {"error": "contact_not_found", "action_id": str(action.id)}

        timezone = await self._resolve_timezone(db, action)
        date_str = str(payload.get("date", ""))
        time_str = str(payload.get("time", ""))
        duration_minutes = int(payload.get("duration_minutes") or 30)

        try:
            scheduled_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(
                tzinfo=_zone_info(timezone)
            )
        except ValueError:
            logger.error(
                "book_appointment action %s has invalid date/time (%r %r)",
                action.id,
                date_str,
                time_str,
            )
            return {"error": "invalid_datetime", "date": date_str, "time": time_str}

        service = BookingService(workspace_id=action.workspace_id, timezone=timezone)
        booking_result = await service.book_appointment(
            date_str=date_str,
            time_str=time_str,
            email=str(payload.get("email") or contact.email or ""),
            contact_name=str(payload.get("name") or contact.full_name or "Customer"),
            duration_minutes=duration_minutes,
            phone_number=payload.get("phone_number") or contact.phone_number,
            service_type=payload.get("call_type"),
        )
        if not booking_result.success:
            return {"error": "slot_unavailable", "detail": booking_result.error}

        if draft is not None:
            await db.delete(draft)
        agent = await load_agent(db, action.agent_id)
        appointment = await finalize_booking(
            db,
            workspace_id=action.workspace_id,
            contact=contact,
            agent=agent,
            scheduled_at=scheduled_at,
            duration_minutes=duration_minutes,
            notes=payload.get("notes"),
            service_type=payload.get("call_type"),
            verify_availability=agent is not None,
        )
        if draft is not None:
            await db.commit()

        logger.info(
            "Approved action %s booked appointment %s at %s",
            action.id,
            appointment.id,
            scheduled_at.isoformat(),
        )
        return {
            "status": "booked",
            "appointment_id": appointment.id,
            "scheduled_at": scheduled_at.isoformat(),
            "timezone": timezone,
        }

    @staticmethod
    async def _validated_text_booking_draft(
        db: AsyncSession,
        action: PendingAction,
        payload: dict[str, Any],
    ) -> ConversationBookingDraft | dict[str, Any] | None:
        """Reject an approved SMS action if its confirmed draft was replaced."""
        marker = payload.get("booking_draft_prepared_at")
        if marker is None:
            return None  # Legacy and voice actions predate persisted SMS drafts.
        context = action.context or {}
        if context.get("source") != "text_conversation":
            return {"error": "booking_draft_context_invalid", "action_id": str(action.id)}
        raw_duration = payload.get("duration_minutes")
        try:
            conversation_id = uuid.UUID(str(context.get("conversation_id", "")))
            expected_prepared_at = datetime.fromisoformat(str(marker))
            if expected_prepared_at.tzinfo is None:
                raise ValueError("booking draft timestamp must include a timezone")
            if not isinstance(raw_duration, (str, int)) or isinstance(raw_duration, bool):
                raise ValueError("booking draft duration must be an integer")
            duration_minutes = int(raw_duration)
        except (TypeError, ValueError):
            return {"error": "booking_draft_changed", "action_id": str(action.id)}

        draft_result = await db.execute(
            select(ConversationBookingDraft).where(
                ConversationBookingDraft.conversation_id == conversation_id,
                ConversationBookingDraft.workspace_id == action.workspace_id,
            )
        )
        draft = draft_result.scalar_one_or_none()
        if draft is None:
            return {"error": "booking_draft_missing", "action_id": str(action.id)}

        prepared_at = draft.prepared_at
        if prepared_at.tzinfo is None:
            prepared_at = prepared_at.replace(tzinfo=UTC)
        payload_matches = (
            expected_prepared_at.astimezone(UTC) == prepared_at.astimezone(UTC)
            and str(payload.get("date")) == draft.date.isoformat()
            and str(payload.get("time")) == draft.time.strftime("%H:%M")
            and str(payload.get("email")) == draft.email
            and duration_minutes == draft.duration_minutes
            and str(payload.get("call_type")) == BookingDraftCallType(draft.call_type).value
        )
        if not payload_matches:
            return {"error": "booking_draft_changed", "action_id": str(action.id)}
        return draft

    @staticmethod
    async def _resolve_contact(db: AsyncSession, action: PendingAction) -> Contact | None:
        """Find the contact this booking belongs to from the action's context.

        The LLM tool arguments carry no contact reference, so the linkage comes
        from the context recorded when the action was queued: ``contact_id``
        directly, a ``conversation_id`` (text channel), or a ``call_id`` that
        matches the call's message (voice channel).
        """
        from app.models.conversation import Message

        context = action.context or {}

        raw_contact_id = context.get("contact_id")
        if raw_contact_id is not None:
            try:
                contact_id = int(raw_contact_id)
            except (TypeError, ValueError):
                contact_id = None
            if contact_id is not None:
                contact = await db.get(Contact, contact_id)
                if contact is not None and contact.workspace_id == action.workspace_id:
                    return contact

        raw_conversation_id = context.get("conversation_id")
        if raw_conversation_id is not None:
            try:
                conversation_id = uuid.UUID(str(raw_conversation_id))
            except (TypeError, ValueError):
                conversation_id = None
            if conversation_id is not None:
                conversation = await db.get(Conversation, conversation_id)
                if conversation is not None and conversation.workspace_id == action.workspace_id:
                    return await db.get(Contact, conversation.contact_id)

        raw_call_id = context.get("call_id")
        if raw_call_id:
            result = await db.execute(
                select(Conversation)
                .join(Message, Message.conversation_id == Conversation.id)
                .where(
                    Message.provider_message_id == str(raw_call_id),
                    Conversation.workspace_id == action.workspace_id,
                )
                .limit(1)
            )
            conversation = result.scalar_one_or_none()
            if conversation is not None:
                return await db.get(Contact, conversation.contact_id)

        return None

    @staticmethod
    async def _resolve_timezone(db: AsyncSession, action: PendingAction) -> str:
        """Return the workspace's IANA zone; the tool payload never carries one."""
        payload_tz = action.action_payload.get("timezone")
        if isinstance(payload_tz, str) and payload_tz:
            return payload_tz

        workspace = await db.get(Workspace, action.workspace_id)
        settings = (workspace.settings if workspace else None) or {}
        workspace_tz = settings.get("timezone")
        return workspace_tz if isinstance(workspace_tz, str) and workspace_tz else DEFAULT_TIMEZONE


@dataclass(slots=True, frozen=True)
class SendSmsActionHandler:
    """Execute a send_sms pending action via the configured text provider."""

    action_type: str = "send_sms"
    provider_factory: Callable[[], Any] | None = None

    async def execute(self, db: AsyncSession, action: PendingAction) -> dict[str, Any]:
        from app.services.idempotency import derive_outbound_key
        from app.services.telephony.text_provider import get_text_message_provider

        payload = action.action_payload
        provider_factory = self.provider_factory or get_text_message_provider
        sms_service = provider_factory()
        # Stable per-pending-action key. A pending action is executed at
        # most once on success; the approval_worker retries this method on
        # transient failure, and the key ensures the SMS isn't sent twice
        # if the prior attempt reached the provider but failed to commit.
        idempotency_key = derive_outbound_key("approval_send_sms", action.id)
        try:
            await sms_service.send_message(
                to_number=payload["to_number"],
                from_number=payload["from_number"],
                body=payload["text"],
                db=db,
                workspace_id=action.workspace_id,
                agent_id=action.agent_id,
                idempotency_key=idempotency_key,
            )
            return {"status": "sent", "to": payload["to_number"]}
        finally:
            await sms_service.close()


class ApprovalGateService:
    """Central decision point: should an action execute immediately or be queued for approval?"""

    def __init__(self, action_handlers: Iterable[ApprovedActionHandler] | None = None) -> None:
        handlers = (
            tuple(action_handlers) if action_handlers is not None else self._default_handlers()
        )
        self._action_handlers = {handler.action_type: handler for handler in handlers}

    @staticmethod
    def _default_handlers() -> tuple[ApprovedActionHandler, ...]:
        book_appointment_handler: ApprovedActionHandler = BookAppointmentActionHandler()
        send_sms_handler: ApprovedActionHandler = SendSmsActionHandler()
        outbound_handler: ApprovedActionHandler = OutboundFollowUpCampaignSuggestionHandler()
        deal_coach_handler: ApprovedActionHandler = DealCoachFollowUpActionHandler()
        launch_campaign_handler: ApprovedActionHandler = LaunchCampaignHandler()
        return (
            book_appointment_handler,
            send_sms_handler,
            outbound_handler,
            deal_coach_handler,
            launch_campaign_handler,
        )

    async def check_and_execute_or_queue(
        self,
        db: AsyncSession | None,
        agent_id: uuid.UUID | None,
        workspace_id: uuid.UUID,
        action_type: str,
        action_payload: dict[str, Any],
        description: str,
        context: dict[str, Any] | None = None,
        urgency: str = "normal",
        require_approval_without_agent: bool = False,
    ) -> tuple[str, dict[str, Any] | None]:
        """Evaluate action against the agent's HumanProfile policy.

        Returns a tuple of (decision, metadata) where decision is one of:
        - "auto": caller should proceed with normal execution
        - "blocked": action is permanently blocked by policy
        - "pending": action queued for human review (metadata has action_id)
        """
        if agent_id is None and not require_approval_without_agent:
            return ("auto", None)

        if db is None:
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                return await self._evaluate(
                    session,
                    agent_id=agent_id,
                    workspace_id=workspace_id,
                    action_type=action_type,
                    action_payload=action_payload,
                    description=description,
                    context=context or {},
                    urgency=urgency,
                    require_approval_without_agent=require_approval_without_agent,
                )

        return await self._evaluate(
            db,
            agent_id=agent_id,
            workspace_id=workspace_id,
            action_type=action_type,
            action_payload=action_payload,
            description=description,
            context=context or {},
            urgency=urgency,
            require_approval_without_agent=require_approval_without_agent,
        )

    async def _evaluate(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID | None,
        workspace_id: uuid.UUID,
        action_type: str,
        action_payload: dict[str, Any],
        description: str,
        context: dict[str, Any],
        urgency: str,
        require_approval_without_agent: bool,
    ) -> tuple[str, dict[str, Any] | None]:
        """Core evaluation logic."""
        profile: HumanProfile | None = None
        if agent_id is not None:
            result = await db.execute(select(HumanProfile).where(HumanProfile.agent_id == agent_id))
            profile = result.scalar_one_or_none()

        if profile is None and not require_approval_without_agent:
            logger.debug(
                "No HumanProfile for agent %s — auto-approving %s",
                agent_id,
                action_type,
            )
            return ("auto", None)

        policy = (
            profile.action_policies.get(action_type, profile.default_policy) if profile else "ask"
        )

        if policy == "auto":
            logger.info("Policy auto-approve for %s on agent %s", action_type, agent_id)
            return ("auto", None)

        if policy == "never":
            logger.info("Policy blocked %s on agent %s", action_type, agent_id)
            return ("blocked", None)

        # policy == "ask" (or any unrecognised value falls through to ask)
        action = await self._create_pending_action(
            db,
            agent_id=agent_id,
            workspace_id=workspace_id,
            action_type=action_type,
            action_payload=action_payload,
            description=description,
            context=context,
            urgency=urgency,
            profile=profile,
        )
        logger.info(
            "Queued PendingAction %s (%s) for agent %s",
            action.id,
            action_type,
            agent_id,
        )
        return ("pending", {"action_id": str(action.id), "description": description})

    async def _create_pending_action(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID | None,
        workspace_id: uuid.UUID,
        action_type: str,
        action_payload: dict[str, Any],
        description: str,
        context: dict[str, Any],
        urgency: str,
        profile: HumanProfile | None,
    ) -> PendingAction:
        """Create a PendingAction row with expiration derived from profile settings."""
        timeout_minutes = profile.auto_reject_timeout_minutes if profile else 1440
        expires_at: datetime | None = None
        if timeout_minutes > 0:
            expires_at = datetime.now(UTC) + timedelta(minutes=timeout_minutes)

        action = PendingAction(
            agent_id=agent_id,
            workspace_id=workspace_id,
            action_type=action_type,
            action_payload=action_payload,
            description=description,
            context=context,
            urgency=urgency,
            status="pending",
            expires_at=expires_at,
        )
        db.add(action)
        await db.commit()
        await db.refresh(action)
        return action

    async def approve_action(
        self,
        db: AsyncSession,
        action_id: uuid.UUID,
        user_id: int,
        channel: str = "web",
    ) -> PendingAction:
        """Mark a pending action as approved."""
        result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
        action = result.scalar_one()

        action.status = "approved"
        action.reviewed_by_id = user_id
        action.reviewed_at = datetime.now(UTC)
        action.review_channel = channel
        await db.commit()
        await db.refresh(action)
        return action

    async def reject_action(
        self,
        db: AsyncSession,
        action_id: uuid.UUID,
        user_id: int,
        reason: str | None = None,
        channel: str = "web",
    ) -> PendingAction:
        """Mark a pending action as rejected."""
        result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
        action = result.scalar_one()

        action.status = "rejected"
        action.reviewed_by_id = user_id
        action.reviewed_at = datetime.now(UTC)
        action.review_channel = channel
        action.rejection_reason = reason
        await db.commit()
        await db.refresh(action)
        return action

    async def execute_approved_action(
        self,
        db: AsyncSession,
        action: PendingAction,
    ) -> dict[str, Any]:
        """Execute an approved action by dispatching to the appropriate service.

        Supported action types:
        - book_appointment -> BookingService
        - send_sms -> TelnyxSMSService
        """
        if action.status != "approved":
            logger.warning(
                "Refusing to execute non-approved action %s with status %s",
                action.id,
                action.status,
            )
            return {
                "error": "action_not_approved",
                "action_id": str(action.id),
                "status": action.status,
            }

        try:
            execution_result = await self._dispatch_action(db, action)
        except Exception as exc:
            logger.exception(
                "Failed to execute approved action %s (%s)",
                action.id,
                action.action_type,
            )
            raise ApprovalActionExecutionError(action.id, action.action_type) from exc

        # Any handler-reported error means the action did not take effect. Marking
        # it "executed" would hide a booking that was never written.
        action.status = "failed" if execution_result.get("error") else "executed"
        action.executed_at = datetime.now(UTC)
        action.execution_result = execution_result
        await db.commit()
        return execution_result

    async def _dispatch_action(
        self,
        db: AsyncSession,
        action: PendingAction,
    ) -> dict[str, Any]:
        """Route an action to the correct service for execution."""
        from app.services.ai.crm_assistant._tool_metadata import get_approved_action_executor

        handler = self._action_handlers.get(action.action_type)
        if handler is not None:
            return await handler.execute(db, action)

        crm_assistant_handler = get_approved_action_executor(action.action_type)
        if crm_assistant_handler is not None:
            result: dict[str, Any] = await crm_assistant_handler(db, action)
            return result

        logger.warning(
            "No handler for action type %s (action %s)",
            action.action_type,
            action.id,
        )
        return {"error": "unsupported_action_type", "type": action.action_type}

    async def _execute_outbound_follow_up_campaign_suggestion(
        self,
        db: AsyncSession,
        action: PendingAction,
    ) -> dict[str, Any]:
        """Acknowledge an approved outbound follow-up campaign suggestion."""
        return await OutboundFollowUpCampaignSuggestionHandler().execute(db, action)

    async def _execute_book_appointment(
        self,
        db: AsyncSession,
        action: PendingAction,
    ) -> dict[str, Any]:
        """Execute a book_appointment action via BookingService."""
        return await BookAppointmentActionHandler().execute(db, action)

    async def _execute_send_sms(
        self,
        db: AsyncSession,
        action: PendingAction,
    ) -> dict[str, Any]:
        """Execute a send_sms action via the configured text provider."""
        return await SendSmsActionHandler().execute(db, action)


approval_gate_service = ApprovalGateService()
