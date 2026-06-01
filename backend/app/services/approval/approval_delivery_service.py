"""Delivery service for HITL approval request notifications.

Mirrors the NudgeDeliveryService pattern — sends SMS + push notifications
to the human operator when an AI agent queues an action for approval.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.human_profile import HumanProfile
from app.models.pending_action import PendingAction
from app.services.outbound.delivery import (
    OutboundDeliveryChannel,
    OutboundDeliveryRequest,
    outbound_delivery_service,
)
from app.services.telephony.phone_number_resolver import get_workspace_sms_number

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ApprovalDeliveryRequest:
    """Fully-resolved pending-action notification request."""

    action: PendingAction
    profile: HumanProfile
    agent_name: str


@dataclass(slots=True, frozen=True)
class ApprovalDeliveryResult:
    """Result from one approval-notification delivery channel."""

    channel: str
    delivered: bool


class ApprovalDeliveryChannelHandler(Protocol):
    """Typed handler contract for a notification channel."""

    @property
    def channel(self) -> str:
        """Delivery channel identifier reported when notification succeeds."""
        ...

    async def deliver(
        self,
        db: AsyncSession,
        request: ApprovalDeliveryRequest,
    ) -> ApprovalDeliveryResult:
        """Attempt delivery and return whether the channel succeeded."""
        ...


@dataclass(slots=True, frozen=True)
class SmsApprovalDeliveryHandler:
    """Deliver approval requests over SMS."""

    channel: str = "sms"

    async def deliver(
        self,
        db: AsyncSession,
        request: ApprovalDeliveryRequest,
    ) -> ApprovalDeliveryResult:
        if not request.profile.phone_number:
            return ApprovalDeliveryResult(channel=self.channel, delivered=False)

        delivered = await self.send_sms(
            db,
            workspace_id=request.action.workspace_id,
            to_number=request.profile.phone_number,
            action_id=request.action.id,
            agent_name=request.agent_name,
            description=request.action.description,
        )
        return ApprovalDeliveryResult(channel=self.channel, delivered=delivered)

    async def send_sms(
        self,
        db: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        to_number: str,
        action_id: uuid.UUID,
        agent_name: str,
        description: str,
    ) -> bool:
        """Send an approval request through the configured text provider."""
        phone = await get_workspace_sms_number(db, workspace_id)
        if phone is None:
            logger.debug("No from_number for workspace %s", workspace_id)
            return False

        message = f"[{agent_name}] wants to: {description}. Reply Y to approve, N to reject."
        try:
            result = await outbound_delivery_service.deliver(
                db,
                OutboundDeliveryRequest(
                    workspace_id=workspace_id,
                    channel=OutboundDeliveryChannel.SMS,
                    to=to_number,
                    from_=phone.phone_number,
                    body=message,
                    phone_number_id=phone.id,
                    idempotency_scope="approval_notification_sms",
                    idempotency_parts=(action_id,),
                    action_type="approval_notification_sms",
                ),
            )
            return result.delivered
        except Exception:
            logger.exception(
                "Failed to send approval text to %s for workspace %s",
                to_number,
                workspace_id,
            )
            return False


@dataclass(slots=True, frozen=True)
class PushApprovalDeliveryHandler:
    """Deliver approval requests over push notifications."""

    channel: str = "push"

    async def deliver(
        self,
        db: AsyncSession,
        request: ApprovalDeliveryRequest,
    ) -> ApprovalDeliveryResult:
        delivered = await self.send_push(
            db,
            workspace_id=request.action.workspace_id,
            action=request.action,
            agent_name=request.agent_name,
        )
        return ApprovalDeliveryResult(channel=self.channel, delivered=delivered)

    async def send_push(
        self,
        db: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        action: PendingAction,
        agent_name: str,
    ) -> bool:
        """Send push notification to workspace members about a pending action."""
        try:
            result = await outbound_delivery_service.deliver(
                db,
                OutboundDeliveryRequest(
                    workspace_id=workspace_id,
                    channel=OutboundDeliveryChannel.PUSH,
                    title=f"Approval needed from {agent_name}",
                    body=action.description,
                    data={"type": "approval", "action_id": str(action.id)},
                    idempotency_scope="approval_notification_push",
                    idempotency_parts=(action.id,),
                    action_type="approval_notification_push",
                ),
            )
            return result.delivered
        except Exception:
            logger.exception("Failed to send approval push for action %s", action.id)
            return False


class ApprovalDeliveryService:
    """Delivers approval request notifications via SMS + push."""

    def __init__(
        self, channel_handlers: Iterable[ApprovalDeliveryChannelHandler] | None = None
    ) -> None:
        self._channel_handlers = (
            tuple(channel_handlers)
            if channel_handlers is not None
            else (
                SmsApprovalDeliveryHandler(),
                PushApprovalDeliveryHandler(),
            )
        )

    async def notify_pending_action(self, db: AsyncSession, action: PendingAction) -> bool:
        """Send SMS + push notification about a pending action.

        Returns True if at least one notification channel succeeded.
        """
        # Look up HumanProfile for the agent
        result = await db.execute(
            select(HumanProfile).where(HumanProfile.agent_id == action.agent_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            logger.warning(
                "No HumanProfile for agent %s — cannot notify for action %s",
                action.agent_id,
                action.id,
            )
            return False

        # Load agent name for the SMS message
        agent_result = await db.execute(select(Agent).where(Agent.id == action.agent_id))
        agent = agent_result.scalar_one_or_none()
        agent_name = agent.name if agent else "AI Agent"

        request = ApprovalDeliveryRequest(
            action=action,
            profile=profile,
            agent_name=agent_name,
        )
        results = [await handler.deliver(db, request) for handler in self._channel_handlers]
        delivered_via = [result.channel for result in results if result.delivered]

        if not delivered_via:
            logger.warning(
                "Failed to deliver any notification for action %s",
                action.id,
            )
            return False

        # Mark notification as sent
        action.notification_sent = True
        action.notification_sent_at = datetime.now(UTC)
        await db.commit()

        logger.info(
            "Notified about action %s via %s",
            action.id,
            ", ".join(delivered_via),
        )
        return True

    async def _send_sms(
        self,
        db: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        to_number: str,
        action_id: uuid.UUID,
        agent_name: str,
        description: str,
    ) -> bool:
        """Send an approval request through the configured text provider."""
        return await SmsApprovalDeliveryHandler().send_sms(
            db,
            workspace_id=workspace_id,
            to_number=to_number,
            action_id=action_id,
            agent_name=agent_name,
            description=description,
        )

    async def _send_push(
        self,
        db: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        action: PendingAction,
        agent_name: str,
    ) -> bool:
        """Send push notification to workspace members about a pending action."""
        return await PushApprovalDeliveryHandler().send_push(
            db,
            workspace_id=workspace_id,
            action=action,
            agent_name=agent_name,
        )


approval_delivery_service = ApprovalDeliveryService()
