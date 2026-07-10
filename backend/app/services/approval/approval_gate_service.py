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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.human_profile import HumanProfile
from app.models.pending_action import PendingAction

logger = logging.getLogger(__name__)


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
    """Execute a book_appointment pending action via BookingService."""

    action_type: str = "book_appointment"

    async def execute(self, db: AsyncSession, action: PendingAction) -> dict[str, Any]:
        from app.services.calendar.booking import BookingService

        payload = action.action_payload
        timezone: str = payload.get("timezone", "America/New_York")

        service = BookingService(
            workspace_id=action.workspace_id,
            timezone=timezone,
        )
        booking_result = await service.book_appointment(
            date_str=payload.get("date", ""),
            time_str=payload.get("time", ""),
            email=payload.get("email", ""),
            contact_name=payload.get("name", ""),
            duration_minutes=payload.get("duration_minutes", 30),
            phone_number=payload.get("phone_number"),
        )
        return {"status": "booked", "booking": str(booking_result)}


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

        action.status = (
            "failed" if execution_result.get("error") == "unsupported_action_type" else "executed"
        )
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
