"""Approval worker — processes HITL pending actions.

Runs every 30 seconds to:
1. Send notifications for new pending actions
2. Execute approved actions (book appointment, send SMS, etc.)
3. Auto-approve actions past their timeout, expire old ones
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.human_profile import HumanProfile
from app.models.pending_action import PendingAction
from app.services.approval.approval_delivery_service import ApprovalDeliveryService
from app.services.approval.approval_gate_service import ApprovalGateService
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker


class ApprovalWorker(RetryableWorker, BaseWorker):
    """Processes approved actions, handles timeouts, and sends pending notifications."""

    POLL_INTERVAL_SECONDS = 30
    COMPONENT_NAME = "approval_worker"
    max_retries = 3
    backoff_base_seconds = 2.0

    def __init__(self) -> None:
        super().__init__()
        self.delivery_service = ApprovalDeliveryService()
        self.gate_service = ApprovalGateService()

    async def _process_items(self) -> None:
        """Main cycle. Open a session and run all sub-tasks."""
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await self._send_pending_notifications(db)
            await self._execute_approved_actions(db)
            await self._handle_timeouts(db)

    async def _send_pending_notifications(self, db: AsyncSession) -> None:
        """Find pending actions where notification has not been sent and notify."""
        result = await db.execute(
            select(PendingAction).where(
                and_(
                    PendingAction.status == "pending",
                    PendingAction.notification_sent.is_(False),
                )
            )
        )
        actions = result.scalars().all()

        for action in actions:
            await self.execute_with_retry(
                self._notify_pending_action,
                db,
                action,
                item_key=f"notify:{action.id}",
            )

    async def _notify_pending_action(
        self, db: AsyncSession, action: PendingAction
    ) -> None:
        """Notify a single pending action; raises on failure for retry."""
        try:
            await self.delivery_service.notify_pending_action(db, action)
            await db.commit()
            self.record_items_processed()
        except Exception:
            await db.rollback()
            raise

    async def _execute_approved_actions(self, db: AsyncSession) -> None:
        """Find approved actions and execute them."""
        result = await db.execute(
            select(PendingAction).where(PendingAction.status == "approved")
        )
        actions = result.scalars().all()

        for action in actions:
            await self.execute_with_retry(
                self._execute_single_action,
                db,
                action,
                item_key=f"execute:{action.id}",
            )

    async def _execute_single_action(
        self, db: AsyncSession, action: PendingAction
    ) -> None:
        """Execute a single approved action; raises on failure for retry."""
        try:
            await self.gate_service.execute_approved_action(db, action)
            await db.commit()
            self.record_items_processed()
        except Exception:
            await db.rollback()
            raise

    async def _handle_timeouts(self, db: AsyncSession) -> None:
        """Handle auto-approve timeouts and expiration.

        1. Auto-approve: If a pending action's agent has a HumanProfile with
           auto_approve_timeout_minutes > 0 and the timeout has elapsed,
           set status to 'approved' (next poll will execute it).
        2. Expire: If expires_at is set and has passed, set status to 'expired'.
        """
        now = datetime.now(UTC)

        # --- Auto-approve ---
        pending_result = await db.execute(
            select(PendingAction)
            .where(PendingAction.status == "pending")
            .options(selectinload(PendingAction.agent))
        )
        pending_actions = pending_result.scalars().all()

        # Batch-load human profiles for all relevant agent IDs
        agent_ids = {a.agent_id for a in pending_actions}
        if agent_ids:
            profile_result = await db.execute(
                select(HumanProfile).where(
                    and_(
                        HumanProfile.agent_id.in_(agent_ids),
                        HumanProfile.is_active.is_(True),
                        HumanProfile.auto_approve_timeout_minutes > 0,
                    )
                )
            )
            profiles_by_agent = {
                p.agent_id: p for p in profile_result.scalars().all()
            }

            for action in pending_actions:
                profile = profiles_by_agent.get(action.agent_id)
                if profile is None:
                    continue
                timeout_delta = timedelta(
                    minutes=profile.auto_approve_timeout_minutes
                )
                if now >= action.created_at + timeout_delta:
                    action.status = "approved"
                    self.logger.info(
                        "Auto-approved action after timeout",
                        action_id=str(action.id),
                        timeout_minutes=profile.auto_approve_timeout_minutes,
                    )

            await db.commit()

        # --- Expire ---
        expire_result = await db.execute(
            select(PendingAction).where(
                and_(
                    PendingAction.status == "pending",
                    PendingAction.expires_at.is_not(None),
                    PendingAction.expires_at <= now,
                )
            )
        )
        expired_actions = expire_result.scalars().all()

        for action in expired_actions:
            action.status = "expired"
            self.logger.info(
                "Expired pending action",
                action_id=str(action.id),
            )

        if expired_actions:
            await db.commit()


# Singleton registry
_registry: WorkerRegistry[ApprovalWorker] = WorkerRegistry(ApprovalWorker)
start_approval_worker = _registry.start
stop_approval_worker = _registry.stop
get_approval_worker = _registry.get
