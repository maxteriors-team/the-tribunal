"""Outbound workflow CRM assistant tools."""

from __future__ import annotations

from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler
from app.services.outbound.growth_workflow import OutboundGrowthWorkflowService


class OutboundAssistantTools:
    """Plan higher-level outbound workflows for the CRM assistant."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {"plan_outbound_growth_workflow": self.plan_outbound_growth_workflow}

    async def plan_outbound_growth_workflow(self, args: ToolArguments) -> dict[str, object]:
        service = OutboundGrowthWorkflowService(
            db=self.context.db,
            workspace_id=self.context.workspace_id,
        )
        return await service.plan(args)
