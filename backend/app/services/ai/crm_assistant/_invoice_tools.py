"""Invoice read tools for the CRM assistant.

Read-only. Gated on ``billing:read``, the same capability ``/invoices`` enforces,
so the assistant answers money questions for exactly the people who can already
open the invoices screen — and cannot issue, send, or settle one.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.services.ai.crm_assistant._pagination import listing, parse_limit
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
)
from app.services.ai.crm_assistant._tool_errors import invalid_argument, invalid_id, not_found
from app.services.invoices.invoice_service import InvoiceService

# ``InvoiceResponse`` is already the staff list projection and carries no
# ``public_token``, no ``last_emailed_to``/``manual_payment_reference`` (both
# encrypted PII on the model), and no Stripe ids. It is passed through as-is;
# if that schema ever gains one of those, this tool must switch to an allowlist
# like ``_quote_tools._QUOTE_FIELDS``.
_LINE_ITEM_FIELDS = frozenset({"id", "description", "quantity", "unit_price", "total"})


class InvoiceAssistantTools:
    """Read a workspace's invoices and their payment state."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context
        self.service = InvoiceService(context.db)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_invoices": self.list_invoices,
            "get_invoice": self.get_invoice,
        }

    @staticmethod
    def serialize_invoice(invoice: Any) -> dict[str, Any]:
        payload: dict[str, Any] = invoice.model_dump(mode="json")
        line_items = payload.get("line_items")
        if isinstance(line_items, list):
            payload["line_items"] = [
                {key: value for key, value in item.items() if key in _LINE_ITEM_FIELDS}
                for item in line_items
                if isinstance(item, dict)
            ]
        # Payment rows can carry a manual reference (cheque number, memo); the
        # totals below already answer "how much is outstanding".
        payload.pop("payments", None)
        return payload

    async def list_invoices(self, args: ToolArguments) -> dict[str, object]:
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

        page = await self.service.list_invoices(
            self.context.workspace_id,
            page=1,
            page_size=limit,
            status=status,
            contact_id=contact_id,
        )
        return listing(
            [self.serialize_invoice(invoice) for invoice in page.items],
            total=page.total,
        )

    async def get_invoice(self, args: ToolArguments) -> dict[str, object]:
        invoice_id = parse_uuid(args.get("invoice_id"))
        if invoice_id is None:
            return invalid_id("invoice_id", "Call list_invoices to get a valid invoice id.")
        try:
            invoice = await self.service.get_invoice(self.context.workspace_id, invoice_id)
        except HTTPException:
            return not_found("Invoice", "Call list_invoices to get a visible id.")
        return {"success": True, "data": self.serialize_invoice(invoice)}
