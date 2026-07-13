"""Default pipeline provisioning for workspaces.

Every workspace needs at least one active pipeline with ordered stages so that
the opportunities board has columns to render and the ad-library promotion flow
(:mod:`app.services.outbound.promotion`) can open an opportunity in the
workspace's earliest active pipeline / first stage instead of hitting the
``pipeline is None`` branch.

This module is the single source of truth for the default pipeline shape and
exposes :func:`ensure_default_pipeline`, an idempotent helper used at workspace
creation and by the backfill script
(``scripts/ops/backfill_default_pipelines.py``).
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import Pipeline, PipelineStage

__all__ = [
    "DEFAULT_PIPELINE_DESCRIPTION",
    "DEFAULT_PIPELINE_NAME",
    "DEFAULT_PIPELINE_STAGES",
    "ensure_default_pipeline",
    "get_default_pipeline_first_stage",
]

logger = structlog.get_logger()

DEFAULT_PIPELINE_NAME = "Sales Pipeline"
DEFAULT_PIPELINE_DESCRIPTION = "Default pipeline created automatically for this workspace."

# Ordered stages for the default pipeline. ``order`` is ascending, so the first
# entry is the entry stage the promotion flow drops new opportunities into.
DEFAULT_PIPELINE_STAGES: list[dict[str, object]] = [
    {"name": "New", "order": 0, "probability": 0, "stage_type": "active"},
    {"name": "Qualified", "order": 1, "probability": 25, "stage_type": "active"},
    {"name": "Proposal", "order": 2, "probability": 50, "stage_type": "active"},
    {"name": "Won", "order": 3, "probability": 100, "stage_type": "won"},
    {"name": "Lost", "order": 4, "probability": 0, "stage_type": "lost"},
]


async def ensure_default_pipeline(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> Pipeline:
    """Return the workspace's earliest active pipeline, creating one if absent.

    Idempotent: if any active pipeline already exists, the earliest (by
    ``created_at``) is returned unchanged. Otherwise a default pipeline with the
    standard ordered stages is created. Flushes but does not commit — the caller
    owns the transaction.
    """
    existing = await db.execute(
        select(Pipeline)
        .where(Pipeline.workspace_id == workspace_id, Pipeline.is_active.is_(True))
        .order_by(Pipeline.created_at.asc())
        .limit(1)
    )
    pipeline = existing.scalar_one_or_none()
    if pipeline is not None:
        return pipeline

    pipeline = Pipeline(
        workspace_id=workspace_id,
        name=DEFAULT_PIPELINE_NAME,
        description=DEFAULT_PIPELINE_DESCRIPTION,
        is_active=True,
    )
    db.add(pipeline)
    await db.flush()

    for stage_data in DEFAULT_PIPELINE_STAGES:
        db.add(PipelineStage(pipeline_id=pipeline.id, **stage_data))
    await db.flush()

    logger.info(
        "default_pipeline_provisioned",
        workspace_id=str(workspace_id),
        pipeline_id=str(pipeline.id),
        stage_count=len(DEFAULT_PIPELINE_STAGES),
    )
    return pipeline


async def get_default_pipeline_first_stage(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> tuple[Pipeline, PipelineStage | None]:
    """Return the workspace's default pipeline and its entry (lowest-order) stage.

    Provisions the default pipeline when absent (via :func:`ensure_default_pipeline`)
    so callers that drop new opportunities onto the board always land in a real
    pipeline / first stage instead of the ``pipeline is None`` branch. Flushes but
    does not commit — the caller owns the transaction.
    """
    pipeline = await ensure_default_pipeline(db, workspace_id)
    stage_result = await db.execute(
        select(PipelineStage)
        .where(PipelineStage.pipeline_id == pipeline.id)
        .order_by(PipelineStage.order.asc())
        .limit(1)
    )
    return pipeline, stage_result.scalar_one_or_none()
