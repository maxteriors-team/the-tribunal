"""Offer CRM assistant tools."""

from __future__ import annotations

import uuid
from typing import Any

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.offer import Offer
from app.schemas.offer import OfferCreate, OfferUpdate
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
)


class OfferAssistantTools:
    """Read and mutate outbound offer drafts."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_offers": self.list_offers,
            "get_offer_details": self.get_offer_details,
            "create_offer_draft": self.create_offer_draft,
            "update_offer_draft": self.update_offer_draft,
        }

    @staticmethod
    def serialize_offer_summary(offer: Offer) -> dict[str, Any]:
        return {
            "id": str(offer.id),
            "name": offer.name,
            "description": offer.description,
            "discount_type": offer.discount_type,
            "discount_value": offer.discount_value,
            "is_active": offer.is_active,
            "headline": offer.headline,
            "offer_price": offer.offer_price,
            "cta_text": offer.cta_text,
            "valid_until": offer.valid_until.isoformat() if offer.valid_until else None,
        }

    @classmethod
    def serialize_offer_details(cls, offer: Offer) -> dict[str, Any]:
        return {
            **cls.serialize_offer_summary(offer),
            "terms": offer.terms,
            "valid_from": offer.valid_from.isoformat() if offer.valid_from else None,
            "subheadline": offer.subheadline,
            "regular_price": offer.regular_price,
            "savings_amount": offer.savings_amount,
            "guarantee_type": offer.guarantee_type,
            "guarantee_days": offer.guarantee_days,
            "guarantee_text": offer.guarantee_text,
            "urgency_type": offer.urgency_type,
            "urgency_text": offer.urgency_text,
            "scarcity_count": offer.scarcity_count,
            "value_stack_items": offer.value_stack_items or [],
            "cta_subtext": offer.cta_subtext,
            "is_public": offer.is_public,
            "public_slug": offer.public_slug,
            "require_email": offer.require_email,
            "require_phone": offer.require_phone,
            "require_name": offer.require_name,
            "page_views": offer.page_views,
            "opt_ins": offer.opt_ins,
            "created_at": offer.created_at.isoformat() if offer.created_at else None,
            "updated_at": offer.updated_at.isoformat() if offer.updated_at else None,
        }

    async def get_offer_for_workspace(self, offer_id: uuid.UUID) -> Offer | None:
        return await get_workspace_owned(
            self.context.db,
            Offer,
            offer_id,
            self.context.workspace_id,
        )

    async def list_offers(self, args: ToolArguments) -> dict[str, object]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select_workspace_owned(Offer, self.context.workspace_id)
            .order_by(Offer.created_at.desc())
            .limit(limit)
        )
        if args.get("active_only"):
            stmt = stmt.where(Offer.is_active.is_(True))

        result = await self.context.db.execute(stmt)
        offers = result.scalars().all()

        return {
            "success": True,
            "data": [self.serialize_offer_summary(offer) for offer in offers],
            "count": len(offers),
        }

    async def get_offer_details(self, args: ToolArguments) -> dict[str, object]:
        offer_id = parse_uuid(args.get("offer_id"))
        if offer_id is None:
            return {"success": False, "error": "Invalid offer_id"}

        offer = await self.get_offer_for_workspace(offer_id)
        if offer is None:
            return {"success": False, "error": "Offer not found"}

        return {"success": True, "data": self.serialize_offer_details(offer)}

    async def create_offer_draft(self, args: ToolArguments) -> dict[str, object]:
        try:
            offer_in = OfferCreate(**{**args, "is_active": False})
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        offer = Offer(
            workspace_id=self.context.workspace_id,
            **offer_in.model_dump(mode="json"),
        )
        self.context.db.add(offer)
        await self.context.db.flush()

        return {"success": True, "data": self.serialize_offer_details(offer)}

    async def update_offer_draft(self, args: ToolArguments) -> dict[str, object]:
        offer_id = parse_uuid(args.get("offer_id"))
        if offer_id is None:
            return {"success": False, "error": "Invalid offer_id"}

        offer = await self.get_offer_for_workspace(offer_id)
        if offer is None:
            return {"success": False, "error": "Offer not found"}

        update_args = {key: value for key, value in args.items() if key != "offer_id"}
        try:
            offer_in = OfferUpdate(**update_args)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        update_data = offer_in.model_dump(exclude_unset=True, mode="json")
        if not update_data:
            return {"success": False, "error": "No offer fields provided"}

        for field, value in update_data.items():
            setattr(offer, field, value)

        await self.context.db.flush()

        return {"success": True, "data": self.serialize_offer_details(offer)}
