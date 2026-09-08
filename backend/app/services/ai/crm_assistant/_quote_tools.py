"""Quote/proposal read tools for the CRM assistant.

Read-only by design. Quotes carry money and a customer-facing access token, so
the assistant can answer questions about them but cannot author, send, or
convert one — those stay on the HTTP surface where a human is driving.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.permissions import quote_owner_scope
from app.models.quote import Quote
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


class QuoteAssistantTools:
    """Read a workspace's quotes and proposals."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context
        self.service = QuoteService(context.db)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_quotes": self.list_quotes,
            "get_quote": self.get_quote,
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
