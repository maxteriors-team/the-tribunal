"""Opportunity and pipeline CRM assistant tools."""

from __future__ import annotations

from sqlalchemy import select

from app.db.scope import select_workspace_owned
from app.models.opportunity import Opportunity
from app.models.pipeline import Pipeline, PipelineStage
from app.services.ai.crm_assistant._pagination import count_matching, listing
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler


class OpportunityAssistantTools:
    """Read pipeline and opportunity data for assistant tool calls."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_pipeline_stages": self.list_pipeline_stages,
            "list_opportunities": self.list_opportunities,
        }

    async def list_pipeline_stages(self, args: ToolArguments) -> dict[str, object]:
        """List ordered pipeline stages, always scoped to the current workspace."""

        pipeline_name = str(args.get("pipeline_name") or "").strip()
        stage_name = str(args.get("stage_name") or "").strip()

        stmt = (
            select(Pipeline, PipelineStage)
            .join(PipelineStage, PipelineStage.pipeline_id == Pipeline.id)
            .where(Pipeline.workspace_id == self.context.workspace_id)
        )
        if pipeline_name:
            stmt = stmt.where(Pipeline.name.ilike(f"%{pipeline_name}%"))
        if stage_name:
            stmt = stmt.where(PipelineStage.name.ilike(f"%{stage_name}%"))

        result = await self.context.db.execute(
            stmt.order_by(Pipeline.name.asc(), PipelineStage.order.asc(), PipelineStage.id.asc())
        )
        rows = result.all()

        return listing(
            [
                {
                    "pipeline_id": str(pipeline.id),
                    "pipeline_name": pipeline.name,
                    "pipeline_is_active": pipeline.is_active,
                    "stage_id": str(stage.id),
                    "stage_name": stage.name,
                    "stage_order": stage.order,
                    "stage_type": stage.stage_type,
                    "stage_probability": stage.probability,
                }
                for pipeline, stage in rows
            ],
            total=len(rows),
        )

    async def list_opportunities(self, args: ToolArguments) -> dict[str, object]:
        limit = min(args.get("limit", 10), 50)
        stmt = select_workspace_owned(Opportunity, self.context.workspace_id)

        total = await count_matching(self.context.db, Opportunity, stmt)
        result = await self.context.db.execute(
            stmt.order_by(Opportunity.created_at.desc()).limit(limit)
        )
        opportunities = result.scalars().all()

        return listing(
            [
                {
                    "id": str(opportunity.id),
                    "name": opportunity.name,
                    "status": opportunity.status,
                    "amount": float(opportunity.amount) if opportunity.amount else None,
                    "probability": opportunity.probability,
                    "primary_contact_id": opportunity.primary_contact_id,
                }
                for opportunity in opportunities
            ],
            total=total,
        )
