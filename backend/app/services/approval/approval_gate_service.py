"""Central approval gate for the HITL (Human-In-The-Loop) system.

Decides whether an AI-proposed action should execute immediately,
be blocked, or be queued for human approval based on the agent's
HumanProfile policies.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.human_profile import HumanProfile
from app.models.pending_action import PendingAction

logger = logging.getLogger(__name__)


class ApprovalGateService:
    """Central decision point: should an action execute immediately or be queued for approval?"""

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
        try:
            execution_result = await self._dispatch_action(db, action)
            action.status = "executed"
            action.executed_at = datetime.now(UTC)
            action.execution_result = execution_result
            await db.commit()
            return execution_result
        except Exception:
            logger.exception(
                "Failed to execute approved action %s (%s)",
                action.id,
                action.action_type,
            )
            error_result: dict[str, Any] = {
                "error": "execution_failed",
                "action_id": str(action.id),
            }
            action.status = "failed"
            action.executed_at = datetime.now(UTC)
            action.execution_result = error_result
            await db.commit()
            return error_result

    async def _dispatch_action(
        self,
        db: AsyncSession,
        action: PendingAction,
    ) -> dict[str, Any]:
        """Route an action to the correct service for execution."""
        dispatch_map: dict[str, Any] = {
            "book_appointment": self._execute_book_appointment,
            "send_sms": self._execute_send_sms,
            "crm_assistant.start_campaign": self._execute_crm_assistant_campaign_lifecycle,
            "crm_assistant.resume_campaign": self._execute_crm_assistant_campaign_lifecycle,
            "outbound_improvement.follow_up_campaign": (
                self._execute_outbound_follow_up_campaign_suggestion
            ),
        }

        handler = dispatch_map.get(action.action_type)
        if handler is None:
            logger.warning(
                "No handler for action type %s (action %s)",
                action.action_type,
                action.id,
            )
            return {"error": "unsupported_action_type", "type": action.action_type}

        result: dict[str, Any] = await handler(db, action)
        return result

    async def _execute_outbound_follow_up_campaign_suggestion(
        self,
        db: AsyncSession,
        action: PendingAction,
    ) -> dict[str, Any]:
        """Acknowledge an approved outbound follow-up campaign suggestion."""
        return {
            "status": "acknowledged",
            "recommendation": action.action_payload.get("recommended_campaign", {}),
            "source": action.context.get("source"),
            "dedupe_key": action.context.get("dedupe_key"),
        }

    async def _execute_book_appointment(
        self,
        db: AsyncSession,
        action: PendingAction,
    ) -> dict[str, Any]:
        """Execute a book_appointment action via BookingService."""
        from app.services.calendar.booking import BookingService

        payload = action.action_payload
        api_key: str = payload.get("api_key", "")
        event_type_id: int = payload.get("event_type_id", 0)
        timezone: str = payload.get("timezone", "America/New_York")

        service = BookingService(
            api_key=api_key,
            event_type_id=event_type_id,
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

    async def _execute_crm_assistant_campaign_lifecycle(
        self,
        db: AsyncSession,
        action: PendingAction,
    ) -> dict[str, Any]:
        """Execute an approved CRM assistant campaign lifecycle action."""
        from app.services.campaigns.campaign_lifecycle import (
            CampaignLifecycleError,
            get_campaign_for_workspace,
            resume_campaign,
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
            if action.action_type == "crm_assistant.start_campaign":
                lifecycle_result = await start_campaign(db, campaign)
            else:
                lifecycle_result = await resume_campaign(db, campaign)
        except CampaignLifecycleError as exc:
            return {
                "error": "campaign_lifecycle_failed",
                "message": str(exc),
                "campaign_id": str(campaign_id),
            }

        return {
            "status": lifecycle_result.status.value,
            "message": lifecycle_result.message,
            "campaign_id": str(campaign_id),
            "contact_count": lifecycle_result.contact_count,
        }

    async def _execute_send_sms(
        self,
        db: AsyncSession,
        action: PendingAction,
    ) -> dict[str, Any]:
        """Execute a send_sms action via TelnyxSMSService."""
        from app.core.config import settings
        from app.services.telephony.idempotency import derive as derive_idempotency_key
        from app.services.telephony.telnyx import TelnyxSMSService

        payload = action.action_payload
        sms_service = TelnyxSMSService(api_key=settings.telnyx_api_key)
        # Stable per-pending-action key. A pending action is executed at
        # most once on success; the approval_worker retries this method on
        # transient failure, and the key ensures the SMS isn't sent twice
        # if the prior attempt reached Telnyx but failed to commit.
        idempotency_key = derive_idempotency_key("approval_send_sms", action.id)
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


approval_gate_service = ApprovalGateService()
