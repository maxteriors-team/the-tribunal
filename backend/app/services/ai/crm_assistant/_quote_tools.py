"""Quote/proposal tools for the CRM assistant.

Mostly read-only, and the one exception is deliberately narrow.

Quotes carry money and a customer-facing access token, so the assistant may
answer questions about them and may *draft* one — but it cannot send, approve,
or convert a quote. Those stay on the HTTP surface where a human is driving.

:meth:`QuoteAssistantTools.create_quote` is that exception, and it is safe for
two reasons that must both hold:

1. **The model cannot name a price.** The tool schema has no price field at all.
   Lines are ``catalog_item_id`` + ``quantity``, and the unit price is read from
   the workspace price book server-side. A model that hallucinates "roofline is
   $800" cannot express that here; the worst it can do is pick the wrong item,
   which the operator sees on the approval card.
2. **It is queued for human approval before the row exists.** ``create_quote``
   is registered ``requires_approval``, so the operator sees the customer, the
   items and the resolved total before anything is written.

The draft is never sent, so no customer-facing token is minted, and what comes
back stays inside the same ``_QUOTE_FIELDS`` allowlist as every read.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.permissions import quote_owner_scope
from app.models.catalog import CatalogItem
from app.models.quote import Quote
from app.schemas.quote import QuoteCreate, QuoteLineItemCreate
from app.services.ai.crm_assistant._pagination import listing, parse_limit
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
)
from app.services.ai.crm_assistant._tool_errors import invalid_argument, invalid_id, not_found
from app.services.quotes.ownership import quote_owner_predicate
from app.services.quotes.quote_service import QuoteService

# A drafted quote is capped well below what the UI allows: the operator has to
# read every line on the approval card, and a 50-line wall of text is a card
# nobody actually checks.
_MAX_QUOTE_LINES = 20

# Placeholder returned alongside a rejection, so the tuple shape stays uniform.
# Callers must check the rejection, never read this.
_REJECTED_LINE = (uuid.UUID(int=0), 0.0)

# Quote fields the assistant may see — an allowlist, never a denylist.
#
# ``QuoteResponse`` also carries ``public_token``: the unguessable key to the
# customer-facing ``/p/quotes/{token}`` proposal page. Everything a tool returns
# becomes model context, which can be quoted back into a reply or an outbound
# SMS, and inbound customer text reaching that same context is attacker
# controlled. So the token never enters it, and neither do the Stripe
# session/intent ids. Adding a field here is a deliberate disclosure decision.
_QUOTE_FIELDS = frozenset(
    {
        "id",
        "number",
        "title",
        "status",
        "contact_id",
        "opportunity_id",
        "assigned_user_id",
        "service_location_id",
        "subtotal",
        "tax_amount",
        "discount_amount",
        "total",
        "currency",
        "deposit_percentage",
        "deposit_amount_fixed",
        "deposit_paid_at",
        "deposit_payment_method",
        "issue_date",
        "expiry_date",
        "sent_at",
        "approved_at",
        "declined_at",
        "decline_reason",
        "notes",
        "terms",
        "primary_service",
        "converted_job_id",
        "converted_invoice_id",
        "first_viewed_at",
        "last_viewed_at",
        "view_count",
        "revision_number",
        "created_at",
        "updated_at",
    }
)


def _parse_one_line(
    line: object,
) -> tuple[tuple[uuid.UUID, float], dict[str, object] | None]:
    """Validate a single requested line into (catalog id, quantity)."""
    if not isinstance(line, dict):
        return _REJECTED_LINE, invalid_argument(
            "Each line item must be an object.",
            "Pass catalog_item_id and quantity for every line.",
        )
    item_id = parse_uuid(line.get("catalog_item_id"))
    if item_id is None:
        return _REJECTED_LINE, invalid_id(
            "catalog_item_id", "Call list_catalog_items to get valid catalog item ids."
        )
    try:
        quantity = float(line.get("quantity", 1))
    except (TypeError, ValueError):
        return _REJECTED_LINE, invalid_argument(
            "quantity must be a number.", "Pass a positive quantity for every line."
        )
    if quantity <= 0:
        return _REJECTED_LINE, invalid_argument(
            "quantity must be greater than zero.",
            "Drop the line instead of quoting a zero quantity.",
        )
    return (item_id, quantity), None


def _parse_requested_lines(
    raw_lines: object,
) -> tuple[list[tuple[uuid.UUID, float]], dict[str, object] | None]:
    """Validate the model's line items into (catalog id, quantity) pairs.

    Split out from the handler so the validation reads as one list of rules
    rather than a stack of early returns inside the write path. Returns the
    parsed lines, or ``(_, rejection)`` describing the first problem — never
    both.

    Note what is absent: there is no price to validate, because the schema has
    no price field. Quantity is the only number the model controls.
    """
    if not isinstance(raw_lines, list) or not raw_lines:
        return [], invalid_argument(
            "create_quote needs at least one line item.",
            "Call list_catalog_items and pass catalog_item_id plus quantity for each line.",
        )
    if len(raw_lines) > _MAX_QUOTE_LINES:
        return [], invalid_argument(
            f"A drafted quote is limited to {_MAX_QUOTE_LINES} line items.",
            "Group the work into fewer catalog items and call it again.",
        )

    requested: list[tuple[uuid.UUID, float]] = []
    for line in raw_lines:
        parsed, rejection = _parse_one_line(line)
        if rejection is not None:
            return [], rejection
        requested.append(parsed)
    return requested, None


class QuoteAssistantTools:
    """Read a workspace's quotes and proposals."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context
        self.service = QuoteService(context.db)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_quotes": self.list_quotes,
            "get_quote": self.get_quote,
            "create_quote": self.create_quote,
        }

    @staticmethod
    def serialize_quote(quote: Any) -> dict[str, Any]:
        """Project a quote response onto the disclosed-field allowlist."""

        payload = quote.model_dump(mode="json")
        return {key: value for key, value in payload.items() if key in _QUOTE_FIELDS}

    def _owner_scope(self) -> int | None:
        """The user id this caller's quote reads are confined to, if any.

        Mirrors ``quote_owner_scope`` as used by ``/quotes``: the sales tier sees
        only quotes assigned to (or created by) them. Keeping the same helper
        means the assistant can never become a side door around that boundary.
        """
        return quote_owner_scope(self.context.role, self.context.user_id)

    async def list_quotes(self, args: ToolArguments) -> dict[str, object]:
        limit = parse_limit(args.get("limit"), default=10, maximum=50)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 50.")

        contact_id = args.get("contact_id")
        if contact_id is not None and (
            isinstance(contact_id, bool) or not isinstance(contact_id, int)
        ):
            return invalid_argument("contact_id must be an integer contact id.")

        status = args.get("status")
        if status is not None and not isinstance(status, str):
            return invalid_argument("status must be a string.")

        page = await self.service.list_quotes(
            self.context.workspace_id,
            page=1,
            page_size=limit,
            status=status,
            contact_id=contact_id,
            owner_user_id=self._owner_scope(),
        )
        return listing(
            [self.serialize_quote(quote) for quote in page.items],
            total=page.total,
        )

    async def get_quote(self, args: ToolArguments) -> dict[str, object]:
        quote_id = parse_uuid(args.get("quote_id"))
        if quote_id is None:
            return invalid_id("quote_id", "Call list_quotes to get a valid quote id.")

        # ``QuoteService.get_quote`` takes no owner-scope argument, so gate on the
        # same predicate ``/quotes/{id}`` uses before loading anything. Reusing
        # ``quote_owner_predicate`` rather than re-deriving the rule keeps the two
        # surfaces from drifting apart; an out-of-scope id reads as "not found".
        visible = await self.context.db.scalar(
            select(Quote.id).where(
                Quote.id == quote_id,
                Quote.workspace_id == self.context.workspace_id,
                quote_owner_predicate(self._owner_scope()),
            )
        )
        if visible is None:
            return not_found("Quote", "Call list_quotes to get a visible id.")

        quote = await self.service.get_quote(self.context.workspace_id, quote_id)
        return {"success": True, "data": self.serialize_quote(quote)}

    async def create_quote(self, args: ToolArguments) -> dict[str, object]:
        """Draft a quote for a contact, priced from the workspace price book.

        Reaches the handler only after a human approved the pending action — see
        the module docstring for why that plus server-side pricing is what makes
        a write tool acceptable on this surface.
        """
        contact_id = args.get("contact_id")
        if not isinstance(contact_id, int):
            return invalid_id("contact_id", "Call search_contacts to get a valid contact id.")

        requested, rejection = _parse_requested_lines(args.get("line_items"))
        if rejection is not None:
            return rejection

        # Resolve prices from the price book. The model supplied ids and
        # quantities only, so this is the single source of every figure on the
        # draft. Scoped to the workspace and to sellable items, so a stale or
        # cross-tenant id resolves to nothing rather than to someone else's price.
        rows = await self.context.db.execute(
            select(CatalogItem).where(
                CatalogItem.workspace_id == self.context.workspace_id,
                CatalogItem.id.in_([item_id for item_id, _ in requested]),
                CatalogItem.is_active.is_(True),
            )
        )
        catalog = {item.id: item for item in rows.scalars()}

        missing = [str(item_id) for item_id, _ in requested if item_id not in catalog]
        if missing:
            return invalid_argument(
                f"{len(missing)} catalog item(s) are not available in this workspace.",
                "Call list_catalog_items and use ids from that result.",
            )

        line_items = [
            QuoteLineItemCreate(
                name=catalog[item_id].name,
                quantity=quantity,
                unit_price=float(catalog[item_id].unit_price),
                catalog_item_id=item_id,
            )
            for item_id, quantity in requested
        ]

        title = args.get("title")
        quote = await self.service.create_quote(
            self.context.workspace_id,
            QuoteCreate(
                contact_id=contact_id,
                title=str(title) if isinstance(title, str) and title.strip() else None,
                line_items=line_items,
            ),
            created_by_id=self.context.user_id,
        )
        return {
            "success": True,
            "data": self.serialize_quote(quote),
            # Said plainly so the model reports what actually happened: a draft
            # exists, and the customer has not seen anything.
            "message": (
                "Draft quote created. It has not been sent — the operator reviews and "
                "sends it from the quote page."
            ),
        }
