"""Service for delivering human nudges via SMS and push notifications."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.permissions import Capability, role_can
from app.models.human_nudge import HumanNudge
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.nudges.nudge_settings import get_nudge_settings
from app.services.outbound.delivery import (
    OutboundDeliveryChannel,
    OutboundDeliveryRequest,
    outbound_delivery_service,
)
from app.services.telephony.phone_number_resolver import get_workspace_sms_number
from app.utils.timezones import resolve_workspace_timezone

logger = logging.getLogger(__name__)

# Default quiet hours (22:00 – 08:00)
DEFAULT_QUIET_START = "22:00"
DEFAULT_QUIET_END = "08:00"


class NudgeDeliveryService:
    """Delivers pending nudges to workspace members via SMS and push."""

    async def deliver_nudge(self, db: AsyncSession, nudge: HumanNudge) -> bool:
        """Deliver a single nudge. Returns True if delivered."""
        # Load workspace for settings
        result = await db.execute(select(Workspace).where(Workspace.id == nudge.workspace_id))
        workspace = result.scalar_one_or_none()
        if workspace is None:
            logger.warning("Workspace %s not found for nudge %s", nudge.workspace_id, nudge.id)
            return False

        nudge_settings = get_nudge_settings(workspace.settings)
        delivery_channels: list[str] = nudge_settings.get("delivery_channels", ["sms", "push"])

        # Resolve target users
        users = await self._resolve_target_users(db, nudge)
        if not users:
            logger.info("No target users for nudge %s", nudge.id)
            return False

        delivered_via: list[str] = []

        # Push notifications are always user-targeted so legacy workspace nudges
        # cannot broadcast to roles that lack CRM write access.
        if "push" in delivery_channels:
            push_delivered = False
            for user in users:
                try:
                    push_result = await outbound_delivery_service.deliver(
                        db,
                        OutboundDeliveryRequest(
                            workspace_id=nudge.workspace_id,
                            channel=OutboundDeliveryChannel.PUSH,
                            title=nudge.title,
                            body=nudge.message,
                            data={"type": "nudge", "nudge_id": str(nudge.id)},
                            user_id=user.id,
                            idempotency_scope="nudge_push",
                            idempotency_parts=(nudge.id, user.id),
                            action_type="nudge_push",
                        ),
                    )
                    push_delivered = push_delivered or push_result.delivered
                except Exception:
                    logger.exception(
                        "Failed to send push for nudge %s to user %s", nudge.id, user.id
                    )
            if push_delivered:
                delivered_via.append("push")

        # SMS delivery
        if "sms" in delivery_channels and not self._is_quiet_hours(workspace):
            sms_ok = await self._deliver_sms(db, nudge, users)
            if sms_ok:
                delivered_via.append("sms")

        if not delivered_via:
            return False

        # Mark as sent
        nudge.status = "sent"
        nudge.delivered_at = datetime.now(UTC)
        nudge.delivered_via = (
            ",".join(delivered_via) if len(delivered_via) > 1 else delivered_via[0]
        )
        await db.commit()
        return True

    async def deliver_pending_nudges(self, db: AsyncSession, workspace_id: uuid.UUID) -> int:
        """Deliver all pending nudges for a workspace. Returns count delivered.

        Rows are claimed ``FOR UPDATE SKIP LOCKED`` so a second backend replica
        cannot pick up the same pending nudge and deliver it twice. Without the
        claim both replicas read ``status == "pending"`` before either writes
        ``status = "sent"``, and the operator gets duplicate SMS/email.
        """
        result = await db.execute(
            select(HumanNudge)
            .where(
                HumanNudge.workspace_id == workspace_id,
                HumanNudge.status == "pending",
                HumanNudge.due_date <= datetime.now(UTC),
            )
            .with_for_update(skip_locked=True)
        )
        nudges = result.scalars().all()

        count = 0
        for nudge in nudges:
            try:
                if await self.deliver_nudge(db, nudge):
                    count += 1
            except Exception:
                logger.exception("Failed to deliver nudge %s", nudge.id)

        if count > 0:
            logger.info("Delivered %d nudges for workspace %s", count, workspace_id)
        return count

    async def _deliver_sms(
        self,
        db: AsyncSession,
        nudge: HumanNudge,
        users: list[User],
    ) -> bool:
        """Send SMS to eligible users. Returns True if at least one sent."""
        phone = await get_workspace_sms_number(db, nudge.workspace_id)
        if phone is None or not settings.telnyx_api_key:
            return False
        from_number = phone.phone_number

        sms_sent = False
        for user in users:
            if not user.phone_number:
                continue
            try:
                result = await outbound_delivery_service.deliver(
                    db,
                    OutboundDeliveryRequest(
                        workspace_id=nudge.workspace_id,
                        channel=OutboundDeliveryChannel.SMS,
                        to=user.phone_number,
                        from_=from_number,
                        body=nudge.message,
                        user=user,
                        phone_number_id=phone.id,
                        idempotency_scope="nudge_sms",
                        idempotency_parts=(nudge.id, user.id),
                        action_type="nudge_sms",
                    ),
                )
                sms_sent = sms_sent or result.delivered
            except Exception:
                logger.exception("Failed to send nudge SMS to user %s", user.id)
        return sms_sent

    async def _resolve_target_users(self, db: AsyncSession, nudge: HumanNudge) -> list[User]:
        """Resolve assigned members, or CRM writers for legacy global nudges."""
        if nudge.assigned_to_user_id is not None:
            result = await db.execute(
                select(User)
                .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
                .where(
                    User.id == nudge.assigned_to_user_id,
                    User.is_active.is_(True),
                    WorkspaceMembership.workspace_id == nudge.workspace_id,
                )
            )
            user = result.scalar_one_or_none()
            return [user] if user else []

        membership_result = await db.execute(
            select(WorkspaceMembership)
            .options(selectinload(WorkspaceMembership.user))
            .where(WorkspaceMembership.workspace_id == nudge.workspace_id)
        )
        memberships: list[WorkspaceMembership] = list(membership_result.scalars().all())
        return [
            membership.user
            for membership in memberships
            if membership.user
            and membership.user.is_active
            and role_can(membership.role, Capability.CRM_WRITE)
        ]

    def _is_quiet_hours(self, workspace: Workspace) -> bool:
        """Check if current time is within quiet hours."""
        nudge_settings = get_nudge_settings(workspace.settings)
        quiet_hours: dict[str, str] = nudge_settings.get("quiet_hours", {})
        start_str = quiet_hours.get("start", DEFAULT_QUIET_START)
        end_str = quiet_hours.get("end", DEFAULT_QUIET_END)

        try:
            start_hour, start_min = (int(x) for x in start_str.split(":"))
            end_hour, end_min = (int(x) for x in end_str.split(":"))
        except (ValueError, AttributeError):
            return False

        # Quiet hours are configured as workspace-local wall-clock times, so the
        # comparison must happen in the workspace timezone. Evaluating in UTC
        # would fire nudges in the middle of the night for non-UTC workspaces
        # (e.g. "quiet until 08:00" ends at 08:00 UTC = 03:00 US-Eastern) — which
        # is exactly what the UTC fallback did, since no workspace sets this key.
        now = datetime.now(resolve_workspace_timezone(workspace))
        current_minutes = now.hour * 60 + now.minute
        start_minutes = start_hour * 60 + start_min
        end_minutes = end_hour * 60 + end_min

        if start_minutes > end_minutes:
            # Quiet hours span midnight (e.g. 22:00 - 08:00)
            return current_minutes >= start_minutes or current_minutes < end_minutes
        else:
            return start_minutes <= current_minutes < end_minutes


nudge_delivery_service = NudgeDeliveryService()
