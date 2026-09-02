"""Move configured deals when their linked Tribunal invoice advances."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.opportunity import Opportunity, OpportunityActivity, OpportunityTask
from app.models.pipeline import Pipeline, PipelineStage
from app.models.workspace import Workspace
from app.schemas.deal_lifecycle import DealLifecycleSettings
from app.services.opportunities.lifecycle_config import get_deal_lifecycle_config
from app.services.opportunities.opportunity_service import OpportunityService

if TYPE_CHECKING:
    from app.models.invoice import Invoice

logger = structlog.get_logger().bind(component="invoice_opportunity_lifecycle")

InvoiceTransition = Literal["sent", "paid"]
_TERMINAL_STATUSES = frozenset({"won", "lost", "abandoned"})
FOLLOW_UP_DELAYS_HOURS = (24, 72)


async def _configured_target(
    db: AsyncSession,
    invoice: Invoice,
    transition: InvoiceTransition,
) -> tuple[DealLifecycleSettings, PipelineStage] | None:
    workspace = await db.get(Workspace, invoice.workspace_id)
    if workspace is None:
        return None
    config = get_deal_lifecycle_config(workspace)
    target_stage_id = (
        config.quote_follow_up_stage_id if transition == "sent" else config.won_stage_id
    )
    if not config.is_configured or target_stage_id is None or config.pipeline_id is None:
        return None

    expected_stage_type = "active" if transition == "sent" else "won"
    target_stage = await db.scalar(
        select(PipelineStage)
        .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
        .where(
            Pipeline.workspace_id == invoice.workspace_id,
            Pipeline.id == config.pipeline_id,
            PipelineStage.id == target_stage_id,
            PipelineStage.stage_type == expected_stage_type,
        )
    )
    if target_stage is None:
        logger.warning(
            "invoice_lifecycle_target_invalid",
            workspace_id=str(invoice.workspace_id),
            invoice_id=str(invoice.id),
            transition=transition,
        )
        return None
    return config, target_stage


async def _locked_eligible_opportunity(
    db: AsyncSession,
    invoice: Invoice,
    config: DealLifecycleSettings,
    transition: InvoiceTransition,
) -> Opportunity | None:
    opportunity = await db.scalar(
        select(Opportunity)
        .where(
            Opportunity.id == invoice.opportunity_id,
            Opportunity.workspace_id == invoice.workspace_id,
            Opportunity.pipeline_id == config.pipeline_id,
            Opportunity.is_active.is_(True),
        )
        .with_for_update()
    )
    if opportunity is None:
        return None

    terminal_stage_ids = {
        stage_id
        for stage_id in (
            config.job_completed_stage_id,
            config.unqualified_stage_id,
            config.won_stage_id if transition == "sent" else None,
        )
        if stage_id is not None
    }
    if opportunity.status in _TERMINAL_STATUSES or opportunity.stage_id in terminal_stage_ids:
        return None
    return opportunity


async def _can_advance_sent_stage(
    db: AsyncSession,
    opportunity: Opportunity,
    config: DealLifecycleSettings,
    target_stage: PipelineStage,
) -> bool:
    if opportunity.stage_id is None or opportunity.stage_id == target_stage.id:
        return True
    current_stage = await db.scalar(
        select(PipelineStage).where(
            PipelineStage.id == opportunity.stage_id,
            PipelineStage.pipeline_id == config.pipeline_id,
        )
    )
    return current_stage is not None and current_stage.order <= target_stage.order


def _follow_up_title(invoice: Invoice, delay_hours: int) -> str:
    return f"Call about invoice {invoice.number} ({delay_hours}h no response)"


async def _create_follow_up_tasks(
    db: AsyncSession,
    invoice: Invoice,
    opportunity: Opportunity,
    config: DealLifecycleSettings,
    *,
    now: datetime,
) -> bool:
    titles = {_follow_up_title(invoice, delay) for delay in FOLLOW_UP_DELAYS_HOURS}
    existing = set(
        (
            await db.scalars(
                select(OpportunityTask.title).where(
                    OpportunityTask.opportunity_id == opportunity.id,
                    OpportunityTask.title.in_(titles),
                )
            )
        ).all()
    )
    existing.update(
        task.title
        for task in db.new
        if isinstance(task, OpportunityTask) and task.opportunity_id == opportunity.id
    )
    created = False
    sent_at = invoice.sent_at or now
    for delay_hours in FOLLOW_UP_DELAYS_HOURS:
        title = _follow_up_title(invoice, delay_hours)
        if title in existing:
            continue
        db.add(
            OpportunityTask(
                opportunity_id=opportunity.id,
                title=title,
                notes=f"No response to invoice {invoice.number}; call the customer.",
                due_at=sent_at + timedelta(hours=delay_hours),
                assigned_user_id=config.follow_up_assignee_user_id,
                created_by_id=None,
            )
        )
        created = True
    return created


async def complete_invoice_follow_up_tasks(
    db: AsyncSession,
    invoice: Invoice,
    opportunity: Opportunity,
    *,
    completed_at: datetime,
) -> bool:
    titles = {_follow_up_title(invoice, delay) for delay in FOLLOW_UP_DELAYS_HOURS}
    tasks = list(
        (
            await db.scalars(
                select(OpportunityTask)
                .where(
                    OpportunityTask.opportunity_id == opportunity.id,
                    OpportunityTask.title.in_(titles),
                    OpportunityTask.completed_at.is_(None),
                )
                .with_for_update()
            )
        ).all()
    )
    tasks.extend(
        task
        for task in db.new
        if (
            isinstance(task, OpportunityTask)
            and task.opportunity_id == opportunity.id
            and task.title in titles
            and task.completed_at is None
        )
    )
    for task in tasks:
        task.completed_at = completed_at
    return bool(tasks)


async def transition_invoice_opportunity(
    db: AsyncSession,
    invoice: Invoice,
    *,
    transition: InvoiceTransition,
) -> bool:
    """Apply one configured, tenant-scoped stage transition without committing."""
    if invoice.opportunity_id is None:
        return False

    configured = await _configured_target(db, invoice, transition)
    if configured is None:
        return False
    config, target_stage = configured

    opportunity = await _locked_eligible_opportunity(db, invoice, config, transition)
    if opportunity is None:
        return False

    stage_changed = opportunity.stage_id != target_stage.id
    if transition == "sent" and not await _can_advance_sent_stage(
        db, opportunity, config, target_stage
    ):
        return False

    now = datetime.now(UTC)
    tasks_changed = (
        await _create_follow_up_tasks(db, invoice, opportunity, config, now=now)
        if transition == "sent"
        else await complete_invoice_follow_up_tasks(
            db,
            invoice,
            opportunity,
            completed_at=invoice.paid_at or now,
        )
    )
    status_changed = transition == "paid" and opportunity.status != "won"
    if not stage_changed and not status_changed and not tasks_changed:
        return False

    invoice_ref = f"{invoice.number} ({invoice.id})"
    if stage_changed:
        await OpportunityService(db).move_stage(
            invoice.workspace_id,
            opportunity.id,
            target_stage.id,
            user_id=None,
            source=f"invoice_{transition}",
            description=(
                f"Invoice {invoice_ref} was {transition}; moved deal to {target_stage.name}"
            ),
        )

    if status_changed:
        old_status = opportunity.status
        opportunity.status = "won"
        opportunity.closed_date = (invoice.paid_at or datetime.now(UTC)).date()
        opportunity.closed_by_id = None
        opportunity.lost_reason = None
        db.add(
            OpportunityActivity(
                opportunity_id=opportunity.id,
                user_id=None,
                activity_type="status_changed",
                old_value=old_status,
                new_value="won",
                description=f"Invoice {invoice_ref} was paid in full",
            )
        )

    logger.info(
        "invoice_lifecycle_opportunity_transitioned",
        workspace_id=str(invoice.workspace_id),
        invoice_id=str(invoice.id),
        opportunity_id=str(opportunity.id),
        transition=transition,
        stage_id=str(target_stage.id),
    )
    return True
