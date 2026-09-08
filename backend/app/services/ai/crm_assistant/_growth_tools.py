"""Growth-surface read tools for the CRM assistant.

Three separate revenue sources an operator asks about: add-on work sellable on
today's jobs, the referral partner roster, and the lead magnets running at the
top of the funnel.

Read-only. Each is gated on the capability its own route requires, which differs
per surface -- selling an upsell, managing the roster and running lead capture
are three different jobs in a home-service business, and the tool layer keeps
them that way.
"""

from __future__ import annotations

from app.db.scope import select_workspace_owned
from app.models.lead_magnet import LeadMagnet
from app.services.ai.crm_assistant._pagination import count_matching, listing, parse_limit
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
)
from app.services.ai.crm_assistant._tool_errors import invalid_argument
from app.services.lead_sources.referral_partner_service import ReferralPartnerService
from app.services.upsell.upsell_service import UpsellService


class GrowthAssistantTools:
    """Read upsell opportunities, referral partners and lead magnets."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_upsell_jobs": self.list_upsell_jobs,
            "list_referral_partners": self.list_referral_partners,
            "list_lead_magnets": self.list_lead_magnets,
        }

    async def list_upsell_jobs(self, args: ToolArguments) -> dict[str, object]:
        """Jobs the *caller* can sell an add-on on.

        ``UpsellService.list_jobs`` takes the user id and role and scopes to the
        technician record behind that login, so this is inherently personal: a
        login with no technician record correctly gets an empty list rather than
        the whole board.
        """
        limit = parse_limit(args.get("limit"), default=10, maximum=50)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 50.")

        response = await UpsellService(self.context.db).list_jobs(
            self.context.workspace_id, self.context.user_id, self.context.role
        )
        items = list(response.items)
        return listing(
            [item.model_dump(mode="json") for item in items[:limit]],
            total=len(items),
        )

    async def list_referral_partners(self, args: ToolArguments) -> dict[str, object]:
        limit = parse_limit(args.get("limit"), default=20, maximum=100)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 100.")

        active_only = args.get("active_only")
        if active_only is not None and not isinstance(active_only, bool):
            return invalid_argument("active_only must be a boolean.")

        response = await ReferralPartnerService(self.context.db).list(
            self.context.workspace_id,
            is_active=True if active_only else None,
        )
        items = list(response.items)
        return listing(
            [item.model_dump(mode="json") for item in items[:limit]],
            total=len(items),
        )

    async def list_lead_magnets(self, args: ToolArguments) -> dict[str, object]:
        limit = parse_limit(args.get("limit"), default=20, maximum=100)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 100.")

        active_only = args.get("active_only")
        if active_only is not None and not isinstance(active_only, bool):
            return invalid_argument("active_only must be a boolean.")

        query = select_workspace_owned(LeadMagnet, self.context.workspace_id)
        if active_only:
            query = query.where(LeadMagnet.is_active.is_(True))

        total = await count_matching(self.context.db, LeadMagnet, query)
        result = await self.context.db.execute(
            query.order_by(LeadMagnet.created_at.desc()).limit(limit)
        )
        magnets = result.scalars().all()
        return listing(
            [
                {
                    "id": str(magnet.id),
                    "name": magnet.name,
                    "magnet_type": magnet.magnet_type,
                    "is_active": magnet.is_active,
                    "created_at": magnet.created_at.isoformat() if magnet.created_at else None,
                }
                for magnet in magnets
            ],
            total=total,
        )
