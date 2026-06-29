"""Approval worker — processes HITL pending actions.

Runs every 30 seconds to:
1. Send notifications for new pending actions
2. Execute approved actions (book appointment, send SMS, etc.)
3. Auto-approve actions past their timeout, expire old ones
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.human_profile import HumanProfile
from app.models.pending_action import PendingAction
from app.services.approval.approval_delivery_service import ApprovalDeliveryService
from app.services.approval.approval_gate_service import ApprovalGateService
from app.services.idempotency import derive_worker_retry_key
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker


class ApprovalWorker(RetryableWorker, BaseWorker):
    """Processes approved actions, handles timeouts, and sends pending notifications."""

    POLL_INTERVAL_SECONDS = 30
    COMPONENT_NAME = "approval_worker"
    # Approved actions hit Telnyx/Cal.com per item — keep modest to avoid
    # bursting external APIs when a backlog drains.
    MAX_CONCURRENCY = 5
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
                action.id,
                item_key=derive_worker_retry_key("notify", action.id),
            )

    async def _notify_pending_action(self, db: AsyncSession, action_id: UUID) -> None:
        """Notify a single pending action; raises on failure for retry.

        Takes the action *id* and re-loads the row on every attempt. A prior
        failed attempt calls ``db.rollback()``, which expires every ORM
        instance in the session; reusing that stale ``action`` would trigger a
        lazy attribute refresh outside the async greenlet context
        (``MissingGreenlet``). Loading inside the awaited ``db.get`` keeps each
        retry on a live, fully-populated instance.
        """
        try:
            action = await db.get(PendingAction, action_id)
            if action is None:
                return
            delivered = await self.delivery_service.notify_pending_action(db, action)
            if not delivered:
                raise RuntimeError(
                    f"approval notification delivery failed for action {action_id}"
                )
            await db.commit()
            self.record_items_processed()
        except Exception:
            await db.rollback()
            raise

    async def _execute_approved_actions(self, db: AsyncSession) -> None:
        """Find approved actions and execute them."""
        result = await db.execute(select(PendingAction).where(PendingAction.status == "approved"))
        actions = result.scalars().all()

        for action in actions:
            await self.execute_with_retry(
                self._execute_single_action,
                db,
                action.id,
                item_key=derive_worker_retry_key("execute", action.id),
            )

    async def _execute_single_action(self, db: AsyncSession, action_id: UUID) -> None:
        """Execute a single approved action; raises on failure for retry.

        Re-loads the action by id each attempt for the same reason as
        :meth:`_notify_pending_action`: a rolled-back retry expires the prior
        ORM instance, so reusing it would lazy-load outside the greenlet.
        """
        try:
            action = await db.get(PendingAction, action_id)
            if action is None:
                return
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
        2. Reject: If expires_at is set and has passed, set status to 'rejected'.
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
        agent_ids = {a.agent_id for a in pending_actions if a.agent_id is not None}
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
            profiles_by_agent = {p.agent_id: p for p in profile_result.scalars().all()}

            for action in pending_actions:
                if action.agent_id is None:
                    continue
                profile = profiles_by_agent.get(action.agent_id)
                if profile is None:
                    continue
                timeout_delta = timedelta(minutes=profile.auto_approve_timeout_minutes)
                if now >= action.created_at + timeout_delta:
                    action.status = "approved"
                    self.logger.info(
                        "Auto-approved action after timeout",
                        action_id=str(action.id),
                        timeout_minutes=profile.auto_approve_timeout_minutes,
                    )

            await db.commit()

        # --- Auto-reject expired actions ---
        expired_result = await db.execute(
            select(PendingAction).where(
                and_(
                    PendingAction.status == "pending",
                    PendingAction.expires_at.is_not(None),
                    PendingAction.expires_at <= now,
                )
            )
        )
        expired_actions = expired_result.scalars().all()

        for action in expired_actions:
            action.status = "rejected"
            action.reviewed_at = now
            action.review_channel = "timeout"
            action.rejection_reason = "Approval request timed out."
            self.logger.info(
                "Auto-rejected pending action after timeout",
                action_id=str(action.id),
            )

        if expired_actions:
            await db.commit()


# Singleton registry
_registry: WorkerRegistry[ApprovalWorker] = WorkerRegistry(ApprovalWorker)
start_approval_worker = _registry.start
stop_approval_worker = _registry.stop
get_approval_worker = _registry.get
