"""Move a linked deal when an installation job is completed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.opportunity import Opportunity, OpportunityActivity
from app.models.pipeline import Pipeline, PipelineStage
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.deal_lifecycle import DealLifecycleSettings
from app.services.opportunities.lifecycle_config import get_deal_lifecycle_config
from app.services.opportunities.opportunity_service import OpportunityService

if TYPE_CHECKING:
    from app.models.field_service import Job

logger = structlog.get_logger().bind(component="installation_opportunity_lifecycle")


async def _linked_opportunity_id(db: AsyncSession, job: Job) -> uuid.UUID | None:
    opportunity_ids: set[uuid.UUID] = set()
    if job.source_quote_id is not None:
        quote_opportunity_id = await db.scalar(
            select(Quote.opportunity_id).where(
                Quote.id == job.source_quote_id,
                Quote.workspace_id == job.workspace_id,
            )
        )
        if quote_opportunity_id is not None:
            opportunity_ids.add(quote_opportunity_id)
    if job.invoice_id is not None:
        invoice_opportunity_id = await db.scalar(
            select(Invoice.opportunity_id).where(
                Invoice.id == job.invoice_id,
                Invoice.workspace_id == job.workspace_id,
            )
        )
        if invoice_opportunity_id is not None:
            opportunity_ids.add(invoice_opportunity_id)
    if len(opportunity_ids) > 1:
        logger.warning(
            "completed_job_opportunity_conflict",
            workspace_id=str(job.workspace_id),
            job_id=str(job.id),
        )
        return None
    return next(iter(opportunity_ids), None)


async def _configured_target(
    db: AsyncSession,
    job: Job,
) -> tuple[DealLifecycleSettings, PipelineStage] | None:
    workspace = await db.get(Workspace, job.workspace_id)
    if workspace is None:
        return None
    config = get_deal_lifecycle_config(workspace)
    if (
        not config.is_configured
        or config.pipeline_id is None
        or config.job_completed_stage_id is None
    ):
        return None
    target = await db.scalar(
        select(PipelineStage)
        .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
        .where(
            Pipeline.workspace_id == job.workspace_id,
            Pipeline.id == config.pipeline_id,
            PipelineStage.id == config.job_completed_stage_id,
        )
    )
    return (config, target) if target is not None else None


async def transition_completed_job_opportunity(
    db: AsyncSession,
    job: Job,
    *,
    now: datetime | None = None,
) -> bool:
    """Move one tenant-scoped deal to Job Completed without committing."""
    opportunity_id = await _linked_opportunity_id(db, job)
    configured = await _configured_target(db, job) if opportunity_id is not None else None
    if opportunity_id is None or configured is None:
        return False
    config, target = configured
    opportunity = await db.scalar(
        select(Opportunity)
        .where(
            Opportunity.id == opportunity_id,
            Opportunity.workspace_id == job.workspace_id,
            Opportunity.pipeline_id == config.pipeline_id,
            Opportunity.is_active.is_(True),
            Opportunity.status.not_in(("lost", "abandoned")),
            Opportunity.stage_id != config.unqualified_stage_id,
        )
        .with_for_update()
    )
    if opportunity is None:
        return False

    stage_changed = opportunity.stage_id != target.id
    status_changed = opportunity.status != "won"
    if not stage_changed and not status_changed:
        return False
    completed_at = now or datetime.now(UTC)
    if stage_changed:
        await OpportunityService(db).move_stage(
            job.workspace_id,
            opportunity.id,
            target.id,
            user_id=None,
            source="installation_completed",
            description=f"Installation job {job.title} ({job.id}) was completed",
        )
    if status_changed:
        old_status = opportunity.status
        opportunity.status = "won"
        opportunity.closed_date = completed_at.date()
        opportunity.closed_by_id = None
        opportunity.lost_reason = None
        db.add(
            OpportunityActivity(
                opportunity_id=opportunity.id,
                user_id=None,
                activity_type="status_changed",
                old_value=old_status,
                new_value="won",
                description=f"Installation job {job.title} was completed",
            )
        )
    logger.info(
        "completed_job_opportunity_transitioned",
        workspace_id=str(job.workspace_id),
        job_id=str(job.id),
        opportunity_id=str(opportunity.id),
        stage_id=str(target.id),
    )
    return True
