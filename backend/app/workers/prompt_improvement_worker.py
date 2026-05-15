"""Prompt improvement worker for automated suggestion generation.

Periodically analyzes agent performance and generates improvement
suggestions for agents with auto_suggest or auto_activate enabled.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.improvement_suggestion import ImprovementSuggestion
from app.models.prompt_version import PromptVersion
from app.services.ai.prompt_improvement_service import PromptImprovementService
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker


class PromptImprovementWorker(RetryableWorker, BaseWorker):
    """Generates prompt improvement suggestions automatically.

    Runs daily to analyze agents with auto_suggest=True and generate
    improvement suggestions. If auto_activate=True, also auto-approves
    suggestions when no pending suggestions exist.
    """

    POLL_INTERVAL_SECONDS = 86400  # Daily
    COMPONENT_NAME = "prompt_improvement"
    max_retries = 3
    backoff_base_seconds = 2.0

    async def _process_items(self) -> None:
        """Process agents with auto-improvement enabled."""
        async with AsyncSessionLocal() as db:
            # Find agents with auto_suggest or auto_activate enabled
            result = await db.execute(
                select(Agent).where(
                    Agent.is_active.is_(True),
                    (Agent.auto_suggest.is_(True) | Agent.auto_activate.is_(True)),
                )
            )
            agents = list(result.scalars().all())

            if not agents:
                self.logger.debug("No agents with auto-improvement enabled")
                return

            self.logger.info("Processing auto-improvement agents", count=len(agents))

            for agent in agents:
                await self.execute_with_retry(
                    self._process_agent,
                    db,
                    agent,
                    item_key=f"agent:{agent.id}",
                )

            await db.commit()

    async def _process_agent(
        self,
        db: AsyncSession,
        agent: Agent,
    ) -> None:
        """Process a single agent for improvement suggestions.

        Args:
            db: Database session
            agent: Agent to process
        """
        log = self.logger.bind(agent_id=str(agent.id), agent_name=agent.name)

        # Get active version
        version_result = await db.execute(
            select(PromptVersion).where(
                PromptVersion.agent_id == agent.id,
                PromptVersion.is_active.is_(True),
                PromptVersion.arm_status == "active",
            )
        )
        active_version = version_result.scalar_one_or_none()

        if not active_version:
            log.debug("No active version, skipping")
            return

        # Check minimum calls threshold
        if active_version.total_calls < agent.auto_improve_min_calls:
            log.debug(
                "Below minimum calls threshold",
                total_calls=active_version.total_calls,
                min_calls=agent.auto_improve_min_calls,
            )
            return

        # Check for existing pending suggestions
        pending_result = await db.execute(
            select(ImprovementSuggestion).where(
                ImprovementSuggestion.agent_id == agent.id,
                ImprovementSuggestion.status == "pending",
            )
        )
        pending_suggestions = list(pending_result.scalars().all())

        if pending_suggestions and not agent.auto_activate:
            log.debug(
                "Pending suggestions exist, skipping generation",
                pending_count=len(pending_suggestions),
            )
            return

        # Initialize service
        service = PromptImprovementService()

        # If auto_activate and there are pending suggestions, approve the first one
        if agent.auto_activate and pending_suggestions:
            top_suggestion = pending_suggestions[0]
            log.info("Auto-activating pending suggestion", suggestion_id=str(top_suggestion.id))

            try:
                await service.approve_suggestion(
                    db=db,
                    suggestion_id=top_suggestion.id,
                    user_id=None,  # System-approved
                    activate=True,
                )
                log.info("Auto-activated suggestion successfully")
            except Exception as e:
                log.error("Failed to auto-activate suggestion", error=str(e))

            return

        # Generate new suggestions
        log.info("Generating improvement suggestions")

        try:
            # Analyze performance
            analysis = await service.analyze_performance(db, active_version)

            # Generate variations (just 1 for auto-mode)
            variations = await service.generate_variations(
                active_version, analysis, num_variations=1
            )

            # Create suggestions
            for variation in variations:
                suggestion = await service.create_suggestion(
                    db=db,
                    version=active_version,
                    variation=variation,
                    analysis_summary=analysis.summary,
                )
                log.info(
                    "Created improvement suggestion",
                    suggestion_id=str(suggestion.id),
                    mutation_type=variation.mutation_type,
                )

                # If auto_activate, approve immediately
                if agent.auto_activate:
                    await service.approve_suggestion(
                        db=db,
                        suggestion_id=suggestion.id,
                        user_id=None,
                        activate=True,
                    )
                    log.info("Auto-activated new suggestion")

        except Exception as e:
            log.error("Failed to generate suggestions", error=str(e))


# Singleton registry
_registry = WorkerRegistry(PromptImprovementWorker)
start_prompt_improvement_worker = _registry.start
stop_prompt_improvement_worker = _registry.stop
get_prompt_improvement_worker = _registry.get
