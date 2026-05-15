"""Experiment evaluation worker for automated A/B test winner detection.

Periodically checks agents with active experiments and:
- Declares winners when statistical confidence is reached
- Eliminates underperforming versions
- Logs experiment lifecycle events for observability
"""

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.prompt_version import PromptVersion
from app.services.ai.bandit_statistics import ComparisonResult, compare_prompt_versions
from app.services.ai.prompt_version_service import PromptVersionService
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker


class ExperimentEvaluationWorker(RetryableWorker, BaseWorker):
    """Background worker for evaluating A/B test experiments.

    Runs hourly to analyze agents with 2+ active prompt versions,
    declaring winners and eliminating underperformers when statistical
    confidence thresholds are met.
    """

    POLL_INTERVAL_SECONDS = 3600  # Hourly
    COMPONENT_NAME = "experiment_evaluation"
    max_retries = 3
    backoff_base_seconds = 2.0

    async def _process_items(self) -> None:
        """Find agents with active experiments and evaluate them."""
        async with AsyncSessionLocal() as db:
            # Subquery: agents with 2+ active versions
            subq = (
                select(PromptVersion.agent_id)
                .where(
                    PromptVersion.is_active.is_(True),
                    PromptVersion.arm_status == "active",
                )
                .group_by(PromptVersion.agent_id)
                .having(func.count() >= 2)
            ).subquery()

            result = await db.execute(
                select(Agent).where(Agent.id.in_(select(subq.c.agent_id)))
            )
            agents = list(result.scalars().all())

            if not agents:
                self.logger.debug("No agents with active experiments")
                return

            self.logger.info("Evaluating experiments", agent_count=len(agents))

            for agent in agents:
                await self.execute_with_retry(
                    self._evaluate_agent,
                    db,
                    agent,
                    item_key=f"agent:{agent.id}",
                )

    async def _evaluate_agent(
        self,
        db: AsyncSession,
        agent: Agent,
    ) -> None:
        """Evaluate a single agent's active experiment."""
        log = self.logger.bind(agent_id=str(agent.id), agent_name=agent.name)

        # Get active versions
        version_result = await db.execute(
            select(PromptVersion).where(
                PromptVersion.agent_id == agent.id,
                PromptVersion.is_active.is_(True),
                PromptVersion.arm_status == "active",
            )
        )
        versions = list(version_result.scalars().all())

        if len(versions) < 2:
            log.debug("Fewer than 2 active versions, skipping")
            return

        # Run statistical comparison
        comparison = compare_prompt_versions(versions)

        log.info(
            "experiment_evaluation",
            recommended_action=comparison.recommended_action,
            winner_id=str(comparison.winner_id) if comparison.winner_id else None,
            winner_probability=comparison.winner_probability,
            min_samples_needed=comparison.min_samples_needed,
            version_count=len(versions),
            auto_evaluate=agent.auto_evaluate,
        )

        version_service = PromptVersionService()

        if comparison.recommended_action == "declare_winner" and agent.auto_evaluate:
            await self._declare_winner(db, log, version_service, comparison, versions)
        elif comparison.recommended_action == "eliminate_worst" and agent.auto_evaluate:
            await self._eliminate_worst(db, log, version_service, comparison, versions)

    async def _declare_winner(
        self,
        db: AsyncSession,
        log: structlog.stdlib.BoundLogger,
        version_service: PromptVersionService,
        comparison: ComparisonResult,
        versions: list[PromptVersion],
    ) -> None:
        """Declare the winning version and deactivate others."""
        winner_id: uuid.UUID | None = comparison.winner_id
        if not winner_id:
            return

        winner_version = next(
            (v for v in versions if v.id == winner_id), None
        )
        if not winner_version:
            return

        log.info(
            "auto_declaring_winner",
            winner_version_number=winner_version.version_number,
            winner_probability=comparison.winner_probability,
        )

        # activate_version deactivates all other versions for this agent
        await version_service.activate_version(db, winner_id)

        log.info(
            "winner_declared",
            winner_version_number=winner_version.version_number,
        )

    async def _eliminate_worst(
        self,
        db: AsyncSession,
        log: structlog.stdlib.BoundLogger,
        version_service: PromptVersionService,
        comparison: ComparisonResult,
        versions: list[PromptVersion],
    ) -> None:
        """Eliminate the worst-performing version."""
        if not comparison.versions:
            return

        # comparison.versions is sorted by probability_best descending
        worst_stats = comparison.versions[-1]
        worst_version = next(
            (v for v in versions if v.id == worst_stats.version_id), None
        )
        if not worst_version:
            return

        log.info(
            "auto_eliminating_worst",
            eliminated_version_number=worst_version.version_number,
            eliminated_probability=worst_stats.probability_best,
        )

        await version_service.eliminate_version(db, worst_version.id)

        log.info(
            "version_eliminated",
            eliminated_version_number=worst_version.version_number,
        )


# Singleton registry
_registry = WorkerRegistry(ExperimentEvaluationWorker)
start_experiment_evaluation_worker = _registry.start
stop_experiment_evaluation_worker = _registry.stop
get_experiment_evaluation_worker = _registry.get
