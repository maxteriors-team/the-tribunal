"""Background workers registry.

Provides centralized lifecycle management for all background workers.
"""

import structlog

# Import all worker registries
from app.workers.approval_worker import _registry as approval_registry
from app.workers.auth_rate_limit_cleanup_worker import (
    _registry as auth_rate_limit_cleanup_registry,
)
from app.workers.automation_worker import _registry as automation_registry
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.campaign_worker import _registry as campaign_registry
from app.workers.drip_campaign_worker import _registry as drip_campaign_registry
from app.workers.enrichment_worker import _registry as enrichment_registry
from app.workers.experiment_evaluation_worker import _registry as experiment_evaluation_registry
from app.workers.followup_worker import _registry as followup_registry
from app.workers.message_test_worker import _registry as message_test_registry
from app.workers.never_booked_worker import _registry as never_booked_registry
from app.workers.noshow_reengagement_worker import _registry as noshow_reengagement_registry
from app.workers.nudge_worker import _registry as nudge_registry
from app.workers.outbound_improvement_suggestion_worker import (
    _registry as outbound_improvement_suggestion_registry,
)
from app.workers.prompt_improvement_worker import _registry as prompt_improvement_registry
from app.workers.prompt_stats_worker import _registry as prompt_stats_registry
from app.workers.reminder_worker import _registry as reminder_registry
from app.workers.reputation_worker import _registry as reputation_registry
from app.workers.transcript_analysis_worker import _registry as transcript_analysis_registry
from app.workers.voice_campaign_worker import _registry as voice_campaign_registry

logger = structlog.get_logger()

# All worker registries in startup order
ALL_REGISTRIES: list[WorkerRegistry[BaseWorker]] = [
    campaign_registry,
    voice_campaign_registry,
    followup_registry,
    reminder_registry,
    message_test_registry,
    reputation_registry,
    enrichment_registry,
    prompt_stats_registry,
    prompt_improvement_registry,
    outbound_improvement_suggestion_registry,
    experiment_evaluation_registry,
    automation_registry,
    noshow_reengagement_registry,
    never_booked_registry,
    nudge_registry,
    approval_registry,
    drip_campaign_registry,
    transcript_analysis_registry,
    auth_rate_limit_cleanup_registry,
]


async def start_all_workers() -> None:
    """Start all background workers in order."""
    log = logger.bind(context="worker_lifecycle")
    for registry in ALL_REGISTRIES:
        worker = await registry.start()
        name = worker.COMPONENT_NAME or worker.__class__.__name__
        log.info("worker_started", worker=name)


async def stop_all_workers() -> None:
    """Stop all background workers in reverse order."""
    log = logger.bind(context="worker_lifecycle")
    for registry in reversed(ALL_REGISTRIES):
        instance = registry.get()
        name = instance.COMPONENT_NAME or instance.__class__.__name__ if instance else "unknown"
        await registry.stop()
        log.info("worker_stopped", worker=name)


__all__ = [
    "start_all_workers",
    "stop_all_workers",
    "ALL_REGISTRIES",
]
