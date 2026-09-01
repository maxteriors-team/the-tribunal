"""Validated per-workspace configuration for deal lifecycle automation."""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import Pipeline, PipelineStage
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.deal_lifecycle import DealLifecycleSettings
from app.services.exceptions import ValidationError

logger = structlog.get_logger()

SETTINGS_KEY = "deal_lifecycle"


def get_deal_lifecycle_config(workspace: Workspace) -> DealLifecycleSettings:
    """Read lifecycle settings, failing closed when stored JSON was corrupted."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        return DealLifecycleSettings(**raw)
    except Exception as exc:  # pragma: no cover - defensive against manual JSONB edits
        logger.warning(
            "deal_lifecycle_config_invalid_blob",
            workspace_id=str(workspace.id),
            error=str(exc),
        )
        return DealLifecycleSettings()


async def validate_deal_lifecycle_references(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    config: DealLifecycleSettings,
) -> None:
    """Ensure every configured resource belongs to the same tenant and pipeline."""
    if not config.is_configured:
        return

    pipeline_id = config.pipeline_id
    assignee_id = config.follow_up_assignee_user_id
    if pipeline_id is None or assignee_id is None:  # guarded by schema validation
        raise ValidationError("Deal lifecycle configuration is incomplete")

    stage_result = await db.execute(
        select(PipelineStage.id)
        .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
        .where(
            Pipeline.workspace_id == workspace_id,
            Pipeline.id == pipeline_id,
            PipelineStage.id.in_(config.stage_ids),
        )
    )
    if set(stage_result.scalars().all()) != set(config.stage_ids):
        raise ValidationError("Lifecycle pipeline and stages must belong to this workspace")

    member_result = await db.execute(
        select(User.id)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            User.id == assignee_id,
            User.is_active.is_(True),
        )
    )
    if member_result.scalar_one_or_none() is None:
        raise ValidationError("Follow-up assignee must be an active member of this workspace")
