"""Outbound improvement suggestion worker.

Runs daily campaign/report analysis and queues follow-up campaign suggestions for
human approval.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.services.ai.outbound_improvement_suggestion_service import (
    OutboundImprovementSuggestionService,
    PeriodName,
    period_window,
)
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker


class OutboundImprovementSuggestionWorker(RetryableWorker, BaseWorker):
    """Generates outbound campaign improvement suggestions automatically."""

    POLL_INTERVAL_SECONDS = 86400  # Daily
    COMPONENT_NAME = "outbound_improvement_suggestions"
    MAX_CONCURRENCY = 3
    max_retries = 3
    backoff_base_seconds = 2.0

    async def _process_items(self) -> None:
        """Process daily suggestions and weekly suggestions on Monday UTC."""
        today = self._today_utc()
        async with AsyncSessionLocal() as db:
            await self._process_period(db, "daily", today)
            if self._should_process_weekly(today):
                await self._process_period(db, "weekly", today)

    async def _process_period(
        self,
        db: AsyncSession,
        period: PeriodName,
        today: date,
    ) -> None:
        """Process all workspaces with evidence for one period."""
        service = OutboundImprovementSuggestionService()
        window = period_window(period, today)
        workspace_result = await db.execute(service.workspace_evidence_query(window))
        workspace_ids = [row[0] for row in workspace_result.all()]

        if not workspace_ids:
            self.logger.debug("No outbound evidence workspaces found", period=window.label)
            return

        self.logger.info(
            "Processing outbound improvement suggestions",
            period=window.label,
            workspace_count=len(workspace_ids),
        )
        for workspace_id in workspace_ids:
            await self.execute_with_retry(
                self._process_workspace_period,
                db,
                workspace_id,
                period,
                today,
                item_key=f"workspace:{workspace_id}:{period}:{window.starts_at.date().isoformat()}",
            )

    async def _process_workspace_period(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        period: PeriodName,
        today: date,
    ) -> None:
        """Generate suggestions for a single workspace and commit on success."""
        service = OutboundImprovementSuggestionService()
        actions = await service.generate_for_workspace_period(db, workspace_id, period, today)
        await db.commit()
        self.logger.info(
            "Outbound improvement workspace processed",
            workspace_id=str(workspace_id),
            period=period,
            suggestions_created=len(actions),
        )

    def _today_utc(self) -> date:
        """Return today's UTC date; split out for tests."""
        return datetime.now(UTC).date()

    @staticmethod
    def _should_process_weekly(today: date) -> bool:
        """Run weekly generation on Monday UTC."""
        return today.weekday() == 0


# Singleton registry
_registry = WorkerRegistry(OutboundImprovementSuggestionWorker)
start_outbound_improvement_suggestion_worker = _registry.start
stop_outbound_improvement_suggestion_worker = _registry.stop
get_outbound_improvement_suggestion_worker = _registry.get
