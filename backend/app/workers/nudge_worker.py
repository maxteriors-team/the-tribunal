"""Nudge worker — generates and delivers human-in-the-loop nudges.

Runs hourly (not every 60s like most workers — nudges are a daily concern).
For each active workspace with nudge_settings enabled:
1. NudgeGeneratorService scans contacts for upcoming dates → creates HumanNudge rows
2. NudgeDeliveryService delivers pending nudges via SMS/push to workspace members
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.human_nudge import HumanNudge
from app.models.workspace import Workspace
from app.services.nudges.nudge_delivery import NudgeDeliveryService
from app.services.nudges.nudge_generator import NudgeGeneratorService
from app.services.nudges.nudge_settings import get_nudge_settings
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker


class NudgeWorker(RetryableWorker, BaseWorker):
    """Background worker for generating and delivering human nudges."""

    POLL_INTERVAL_SECONDS = 3600  # 1 hour
    COMPONENT_NAME = "nudge_worker"
    # One generation + delivery pass per workspace; modest concurrency so
    # nudge SMS sends don't burst across all workspaces simultaneously.
    MAX_CONCURRENCY = 3

    def __init__(self) -> None:
        super().__init__()
        self.generator = NudgeGeneratorService()
        self.delivery = NudgeDeliveryService()

    async def _process_items(self) -> None:
        """Process all workspaces: generate then deliver nudges."""
        async with AsyncSessionLocal() as db:
            await self._process_workspaces(db)

    async def _expire_snoozed_nudges(self, db: AsyncSession) -> int:
        """Reset snoozed nudges back to pending if snooze_until has passed."""
        now = datetime.now(UTC)
        cursor = await db.execute(
            update(HumanNudge)
            .where(
                and_(
                    HumanNudge.status == "snoozed",
                    HumanNudge.snoozed_until <= now,
                )
            )
            .values(status="pending", snoozed_until=None)
        )
        count: int = cursor.rowcount  # type: ignore[attr-defined]
        if count:
            await db.commit()
            self.logger.info("Expired %d snoozed nudges back to pending", count)
        return count

    async def _process_workspaces(self, db: AsyncSession) -> None:
        """Iterate active workspaces and run nudge generation + delivery.

        Only the workspace **ids** are materialized up front, deliberately.
        A per-workspace failure rolls the shared session back, which expires
        every ORM instance in it; iterating live ``Workspace`` rows meant the
        next loop turn touched an expired instance and raised
        ``MissingGreenlet``/``DetachedInstanceError`` out of the whole tick, so
        one bad workspace silently skipped every workspace behind it. Plain
        UUIDs carry no session state and survive a rollback.
        """
        # Un-snooze expired nudges first
        await self._expire_snoozed_nudges(db)

        result = await db.execute(select(Workspace.id).where(Workspace.is_active.is_(True)))
        workspace_ids = list(result.scalars().all())

        for workspace_id in workspace_ids:
            await self.execute_with_retry(
                self._process_single_workspace,
                db,
                workspace_id,
                item_key=f"workspace:{workspace_id}",
            )

    async def _process_single_workspace(self, db: AsyncSession, workspace_id: uuid.UUID) -> None:
        """Generate and deliver nudges for a single workspace.

        Re-loads the workspace by id so every retry attempt starts from a live
        row rather than one expired by the previous attempt's rollback.
        """
        workspace = await db.get(Workspace, workspace_id)
        if workspace is None:
            return

        nudge_settings = get_nudge_settings(workspace.settings)
        if not nudge_settings.get("enabled", True):
            return

        # Phase 1: Generate nudges
        generated = await self.generator.generate_for_workspace(db, workspace)
        if generated:
            self.record_items_processed(generated)
            self.logger.info(
                "Nudges generated",
                workspace_id=str(workspace_id),
                count=generated,
            )

        # Phase 2: Deliver pending nudges
        delivered = await self.delivery.deliver_pending_nudges(db, workspace_id)
        if delivered:
            self.record_items_processed(delivered)
            self.logger.info(
                "Nudges delivered",
                workspace_id=str(workspace_id),
                count=delivered,
            )


# Singleton registry
_registry = WorkerRegistry(NudgeWorker)
start_nudge_worker = _registry.start
stop_nudge_worker = _registry.stop
get_nudge_worker = _registry.get
