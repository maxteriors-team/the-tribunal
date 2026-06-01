"""Opportunity CRM assistant tools."""

from __future__ import annotations

from sqlalchemy import select

from app.models.opportunity import Opportunity
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler


class OpportunityAssistantTools:
    """Read pipeline opportunity data for assistant tool calls."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {"list_opportunities": self.list_opportunities}

    async def list_opportunities(self, args: ToolArguments) -> dict[str, object]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select(Opportunity)
            .where(Opportunity.workspace_id == self.context.workspace_id)
            .order_by(Opportunity.created_at.desc())
            .limit(limit)
        )
        result = await self.context.db.execute(stmt)
        opportunities = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": str(opportunity.id),
                    "name": opportunity.name,
                    "status": opportunity.status,
                    "amount": float(opportunity.amount) if opportunity.amount else None,
                    "probability": opportunity.probability,
                }
                for opportunity in opportunities
            ],
            "count": len(opportunities),
        }
