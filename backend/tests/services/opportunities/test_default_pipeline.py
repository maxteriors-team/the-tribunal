"""Tests for default-pipeline provisioning.

Covers the contract the ad-library promotion flow depends on: every workspace
must resolve to a non-empty active pipeline with ordered stages, and
``ensure_default_pipeline`` must be idempotent.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.pipeline import Pipeline, PipelineStage
from app.models.workspace import Workspace
from app.services.opportunities import (
    DEFAULT_PIPELINE_STAGES,
    OpportunityService,
    ensure_default_pipeline,
)

# Hits the real database, so it is an integration test (deselected by default;
# run with `-m integration`).
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_ensure_default_pipeline_provisions_and_is_idempotent() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Pipe", slug=f"pipe-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()

        # First call provisions a pipeline with the standard ordered stages.
        pipeline = await ensure_default_pipeline(db, ws.id)
        await db.flush()
        assert pipeline.workspace_id == ws.id
        assert pipeline.is_active is True

        stages = (
            (
                await db.execute(
                    select(PipelineStage)
                    .where(PipelineStage.pipeline_id == pipeline.id)
                    .order_by(PipelineStage.order)
                )
            )
            .scalars()
            .all()
        )
        assert [s.name for s in stages] == [s["name"] for s in DEFAULT_PIPELINE_STAGES]
        assert [s.order for s in stages] == list(range(len(DEFAULT_PIPELINE_STAGES)))
        # The entry stage (order 0) is what the promotion flow drops leads into.
        assert stages[0].order == 0

        # Second call is idempotent: returns the same pipeline, creates no duplicate.
        again = await ensure_default_pipeline(db, ws.id)
        await db.flush()
        assert again.id == pipeline.id
        all_pipelines = (
            (await db.execute(select(Pipeline).where(Pipeline.workspace_id == ws.id)))
            .scalars()
            .all()
        )
        assert len(all_pipelines) == 1

        # The opportunities API surfaces the provisioned pipeline with its stages.
        await db.commit()
        listed = await OpportunityService(db).list_pipelines(ws.id)
        assert len(listed) == 1
        assert len(listed[0].stages) == len(DEFAULT_PIPELINE_STAGES)
