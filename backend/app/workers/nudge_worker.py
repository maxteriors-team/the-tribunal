"""Nudge worker — generates and delivers human-in-the-loop nudges.

Runs hourly (not every 60s like most workers — nudges are a daily concern).
For each active workspace with nudge_settings enabled:
1. NudgeGeneratorService scans contacts for upcoming dates → creates HumanNudge rows
2. NudgeDeliveryService delivers pending nudges via SMS/push to workspace members
"""

from datetime import UTC, datetime

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.human_nudge import HumanNudge
from app.models.workspace import Workspace
from app.services.nudges.nudge_delivery import NudgeDeliveryService
from app.services.nudges.nudge_generator import NudgeGeneratorService
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
        """Iterate active workspaces and run nudge generation + delivery."""
        # Un-snooze expired nudges first
        await self._expire_snoozed_nudges(db)

        result = await db.execute(select(Workspace).where(Workspace.is_active.is_(True)))
        workspaces = result.scalars().all()

        for workspace in workspaces:
            nudge_settings = workspace.settings.get("nudge_settings", {})
            if not nudge_settings.get("enabled", True):
                continue

            await self.execute_with_retry(self._process_single_workspace, db, workspace)

    async def _process_single_workspace(self, db: AsyncSession, workspace: Workspace) -> None:
        """Generate and deliver nudges for a single workspace."""
        # Phase 1: Generate nudges
        generated = await self.generator.generate_for_workspace(db, workspace)
        if generated:
            self.record_items_processed(generated)
            self.logger.info(
                "Nudges generated",
                workspace_id=str(workspace.id),
                count=generated,
            )

        # Phase 2: Deliver pending nudges
        delivered = await self.delivery.deliver_pending_nudges(db, workspace.id)
        if delivered:
            self.record_items_processed(delivered)
            self.logger.info(
                "Nudges delivered",
                workspace_id=str(workspace.id),
                count=delivered,
            )


# Singleton registry
_registry = WorkerRegistry(NudgeWorker)
start_nudge_worker = _registry.start
stop_nudge_worker = _registry.stop
get_nudge_worker = _registry.get
