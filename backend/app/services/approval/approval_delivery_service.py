"""Delivery service for HITL approval request notifications.

Mirrors the NudgeDeliveryService pattern — sends SMS + push notifications
to the human operator when an AI agent queues an action for approval.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.human_profile import HumanProfile
from app.models.pending_action import PendingAction
from app.services.idempotency import derive_outbound_key
from app.services.push_notifications import push_notification_service
from app.services.telephony.phone_number_resolver import get_workspace_sms_number
from app.services.telephony.text_provider import get_text_message_provider

logger = logging.getLogger(__name__)


class ApprovalDeliveryService:
    """Delivers approval request notifications via SMS + push."""

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

        delivered_via: list[str] = []

        # SMS delivery
        if profile.phone_number:
            sms_ok = await self._send_sms(
                db,
                workspace_id=action.workspace_id,
                to_number=profile.phone_number,
                agent_name=agent_name,
                action_id=action.id,
                description=action.description,
            )
            if sms_ok:
                delivered_via.append("sms")

        # Push notification to workspace members
        push_ok = await self._send_push(
            db,
            workspace_id=action.workspace_id,
            action=action,
            agent_name=agent_name,
        )
        if push_ok:
            delivered_via.append("push")

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
        phone = await get_workspace_sms_number(db, workspace_id)
        if phone is None:
            logger.debug("No from_number for workspace %s", workspace_id)
            return False

        message = f"[{agent_name}] wants to: {description}. Reply Y to approve, N to reject."
        idempotency_key = derive_outbound_key("approval_notification_sms", action_id)
        sms_service = get_text_message_provider()
        try:
            await sms_service.send_message(
                to_number=to_number,
                from_number=phone.phone_number,
                body=message,
                db=db,
                workspace_id=workspace_id,
                phone_number_id=phone.id,
                idempotency_key=idempotency_key,
            )
            return True
        except Exception:
            logger.exception(
                "Failed to send approval text to %s for workspace %s",
                to_number,
                workspace_id,
            )
            return False
        finally:
            await sms_service.close()

    async def _send_push(
        self,
        db: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        action: PendingAction,
        agent_name: str,
    ) -> bool:
        """Send push notification to workspace members about a pending action."""
        try:
            await push_notification_service.send_to_workspace_members(
                db,
                workspace_id=str(workspace_id),
                title=f"Approval needed from {agent_name}",
                body=action.description,
                data={"type": "approval", "action_id": str(action.id)},
            )
            return True
        except Exception:
            logger.exception("Failed to send approval push for action %s", action.id)
            return False


approval_delivery_service = ApprovalDeliveryService()
