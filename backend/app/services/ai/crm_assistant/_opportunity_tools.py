"""Opportunity CRM assistant tools."""

from __future__ import annotations

from app.db.scope import select_workspace_owned
from app.models.opportunity import Opportunity
from app.services.ai.crm_assistant._pagination import count_matching, listing
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler


class OpportunityAssistantTools:
    """Read pipeline opportunity data for assistant tool calls."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {"list_opportunities": self.list_opportunities}

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
