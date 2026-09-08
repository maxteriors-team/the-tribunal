"""Price book and stock read tools for the CRM assistant.

Read-only. These answer "what do we charge for X" and "what do we have on the
shelf" -- the two questions that otherwise force an operator out of the chat.

Cost visibility is not uniform: ``/inventory/items`` shows unit costs only to
``billing:read``, so this module re-applies that same split rather than assuming
anyone who can see a job can see its margin.
"""

from __future__ import annotations

from typing import Literal

from app.core.permissions import Capability, role_can
from app.services.ai.crm_assistant._pagination import listing, parse_limit
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
)
from app.services.ai.crm_assistant._tool_errors import invalid_argument
from app.services.catalog.catalog_service import CatalogService
from app.services.inventory.inventory_service import InventoryService


def _optional_str(args: ToolArguments, key: str) -> str | None | Literal[False]:
    """Return a string argument, ``None`` if absent, or ``False`` if malformed.

    ``Literal[False]`` rather than ``bool`` so ``is False`` narrows the type for
    the caller; a plain ``bool`` would leave ``True`` in the union forever.
    """
    value = args.get(key)
    if value is None:
        return None
    return value if isinstance(value, str) else False


class CatalogAssistantTools:
    """Read the workspace's price book and tracked stock."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_catalog_items": self.list_catalog_items,
            "list_inventory_items": self.list_inventory_items,
        }

    async def list_catalog_items(self, args: ToolArguments) -> dict[str, object]:
        limit = parse_limit(args.get("limit"), default=20, maximum=100)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 100.")

        search = _optional_str(args, "search")
        if search is False:
            return invalid_argument("search must be a string.")
        kind = _optional_str(args, "kind")
        if kind is False:
            return invalid_argument("kind must be a string.")

        page = await CatalogService(self.context.db).list_items(
            self.context.workspace_id,
            page=1,
            page_size=limit,
            kind=kind,
            search=search,
            include_inactive=False,
        )
        return listing(
            [item.model_dump(mode="json") for item in page.items],
            total=page.total,
        )

    async def list_inventory_items(self, args: ToolArguments) -> dict[str, object]:
        limit = parse_limit(args.get("limit"), default=20, maximum=100)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 100.")

        search = _optional_str(args, "search")
        if search is False:
            return invalid_argument("search must be a string.")

        low_stock_only = args.get("low_stock_only")
        if low_stock_only is not None and not isinstance(low_stock_only, bool):
            return invalid_argument("low_stock_only must be a boolean.")

        # Mirrors ``_can_see_costs`` on the inventory router: stock levels are a
        # jobs-tier fact, unit cost is a billing-tier one.
        include_costs = role_can(self.context.role, Capability.BILLING_READ)
        page = await InventoryService(self.context.db).list_items(
            self.context.workspace_id,
            page=1,
            page_size=limit,
            search=search,
            low_stock_only=bool(low_stock_only),
            include_inactive=False,
            include_costs=include_costs,
        )
        return listing(
            [item.model_dump(mode="json") for item in page.items],
            total=page.total,
            extra={"costs_included": include_costs},
        )
