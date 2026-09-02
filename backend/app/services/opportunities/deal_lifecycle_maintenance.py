"""Scheduled maintenance for configured deal-lifecycle workflows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenancy import mark_session_as_system
from app.models.human_nudge import HumanNudge
from app.models.invoice import Invoice
from app.models.opportunity import Opportunity, OpportunityActivity
from app.models.pipeline import PipelineStage
from app.models.workspace import Workspace
from app.schemas.deal_lifecycle import DealLifecycleSettings
from app.services.exceptions import ValidationError
from app.services.opportunities.invoice_lifecycle import complete_invoice_follow_up_tasks
from app.services.opportunities.lifecycle_config import (
    get_deal_lifecycle_config,
    validate_deal_lifecycle_references,
)
from app.services.opportunities.opportunity_service import OpportunityService
from app.utils.timezones import resolve_workspace_timezone

logger = structlog.get_logger().bind(component="deal_lifecycle_maintenance")
UNPAID_EXPIRY_DAYS = 7
NEW_LEAD_NUDGE_TYPE = "new_lead_cleanup"
_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class LifecycleMaintenanceResult:
    expired_invoices: int = 0
    nudges_created: int = 0
    nudges_resolved: int = 0


@dataclass(frozen=True, slots=True)
class _ConfiguredWorkspace:
    workspace: Workspace
    config: DealLifecycleSettings
    stages: dict[uuid.UUID, PipelineStage]


async def _configured_workspaces(db: AsyncSession) -> list[_ConfiguredWorkspace]:
    # simplification: scans active workspace settings every five minutes; move
    # lifecycle config into an indexed table if the workspace count becomes large.
    workspaces = list(
        (await db.scalars(select(Workspace).where(Workspace.is_active.is_(True)))).all()
    )
    configured: list[_ConfiguredWorkspace] = []
    for workspace in workspaces:
        config = get_deal_lifecycle_config(workspace)
        if not config.is_configured or config.pipeline_id is None:
            continue
        try:
            await validate_deal_lifecycle_references(
                db,
                workspace_id=workspace.id,
                config=config,
            )
        except ValidationError as exc:
            logger.warning(
                "deal_lifecycle_config_invalid",
                workspace_id=str(workspace.id),
                error=str(exc),
            )
            continue
        stages = {
            stage.id: stage
            for stage in (
                await db.scalars(
                    select(PipelineStage).where(
                        PipelineStage.pipeline_id == config.pipeline_id,
                        PipelineStage.id.in_(config.stage_ids),
                    )
                )
            ).all()
        }
        configured.append(_ConfiguredWorkspace(workspace, config, stages))
    return configured


async def _expire_unpaid_invoices(
    db: AsyncSession,
    configured: dict[uuid.UUID, _ConfiguredWorkspace],
    *,
    now: datetime,
) -> int:
    if not configured:
        return 0
    invoices = list(
        (
            await db.scalars(
                select(Invoice)
                .join(Opportunity, Opportunity.id == Invoice.opportunity_id)
                .where(
                    Invoice.workspace_id.in_(configured),
                    Invoice.status.in_(("sent", "overdue")),
                    Invoice.sent_at.is_not(None),
                    Invoice.sent_at <= now - timedelta(days=UNPAID_EXPIRY_DAYS),
                    Opportunity.status == "open",
                    Opportunity.is_active.is_(True),
                )
                .order_by(Invoice.sent_at, Invoice.id)
                .limit(_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    expired = 0
    for invoice in invoices:
        workspace_config = configured[invoice.workspace_id]
        config = workspace_config.config
        target_id = config.unqualified_stage_id
        if target_id is None or target_id not in workspace_config.stages:
            continue
        opportunity = await db.scalar(
            select(Opportunity)
            .where(
                Opportunity.id == invoice.opportunity_id,
                Opportunity.workspace_id == invoice.workspace_id,
                Opportunity.pipeline_id == config.pipeline_id,
                Opportunity.status == "open",
                Opportunity.is_active.is_(True),
            )
            .with_for_update()
        )
        if opportunity is None:
            continue

        if opportunity.stage_id != target_id:
            await OpportunityService(db).move_stage(
                invoice.workspace_id,
                opportunity.id,
                target_id,
                user_id=None,
                source="invoice_unpaid_expiry",
                description=(
                    f"Invoice {invoice.number} ({invoice.id}) remained unpaid for "
                    f"{UNPAID_EXPIRY_DAYS} days"
                ),
            )
        old_status = opportunity.status
        opportunity.status = "lost"
        opportunity.closed_date = now.date()
        opportunity.closed_by_id = None
        opportunity.lost_reason = f"Invoice unpaid after {UNPAID_EXPIRY_DAYS} days"
        db.add(
            OpportunityActivity(
                opportunity_id=opportunity.id,
                user_id=None,
                activity_type="status_changed",
                old_value=old_status,
                new_value="lost",
                description=f"Invoice {invoice.number} expired unpaid",
            )
        )
        await complete_invoice_follow_up_tasks(
            db,
            invoice,
            opportunity,
            completed_at=now,
        )
        expired += 1
    return expired


def _cleanup_nudge_key(workspace_id: uuid.UUID, local_date: str) -> str:
    return f"deal_lifecycle:new_lead_cleanup:{workspace_id}:{local_date}"


async def _reconcile_new_lead_nudges(
    db: AsyncSession,
    workspaces: list[_ConfiguredWorkspace],
    *,
    now: datetime,
) -> tuple[int, int]:
    created = 0
    resolved = 0
    for item in workspaces:
        config = item.config
        new_lead_stage_id = config.new_lead_stage_id
        if new_lead_stage_id is None or new_lead_stage_id not in item.stages:
            continue
        local_now = now.astimezone(resolve_workspace_timezone(item.workspace))
        if local_now.time().replace(tzinfo=None) < config.end_of_day_cutoff:
            continue

        local_date = local_now.date().isoformat()
        dedup_key = _cleanup_nudge_key(item.workspace.id, local_date)
        lead_count = int(
            await db.scalar(
                select(func.count(Opportunity.id)).where(
                    Opportunity.workspace_id == item.workspace.id,
                    Opportunity.pipeline_id == config.pipeline_id,
                    Opportunity.stage_id == new_lead_stage_id,
                    Opportunity.status == "open",
                    Opportunity.is_active.is_(True),
                )
            )
            or 0
        )
        nudge = await db.scalar(
            select(HumanNudge).where(HumanNudge.dedup_key == dedup_key).with_for_update()
        )
        if lead_count:
            message = (
                f"Move {lead_count} open deal{'s' if lead_count != 1 else ''} out of New Lead "
                "before ending the day."
            )
            if nudge is None:
                cutoff_local = datetime.combine(
                    local_now.date(),
                    config.end_of_day_cutoff,
                    tzinfo=local_now.tzinfo,
                )
                db.add(
                    HumanNudge(
                        workspace_id=item.workspace.id,
                        contact_id=None,
                        nudge_type=NEW_LEAD_NUDGE_TYPE,
                        title="Clear the New Lead stage",
                        message=message,
                        suggested_action=None,
                        priority="high",
                        due_date=cutoff_local.astimezone(UTC),
                        status="pending",
                        assigned_to_user_id=config.follow_up_assignee_user_id,
                        dedup_key=dedup_key,
                    )
                )
                created += 1
            else:
                nudge.message = message
                nudge.assigned_to_user_id = config.follow_up_assignee_user_id
                if nudge.status == "acted":
                    nudge.status = "pending"
                    nudge.acted_at = None
            continue

        if nudge is not None and nudge.status in {"pending", "sent", "snoozed"}:
            nudge.status = "acted"
            nudge.acted_at = now
            nudge.snoozed_until = None
            resolved += 1
    return created, resolved


async def run_deal_lifecycle_maintenance(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> LifecycleMaintenanceResult:
    """Expire unpaid deals and reconcile end-of-day New Lead nudges."""
    mark_session_as_system(db, reason="deal lifecycle worker sweeps configured workspaces")
    current_time = now or datetime.now(UTC)
    workspaces = await _configured_workspaces(db)
    configured = {item.workspace.id: item for item in workspaces}
    expired = await _expire_unpaid_invoices(db, configured, now=current_time)
    created, resolved = await _reconcile_new_lead_nudges(db, workspaces, now=current_time)
    await db.flush()
    return LifecycleMaintenanceResult(expired, created, resolved)
