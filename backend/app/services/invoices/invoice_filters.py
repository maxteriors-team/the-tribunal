"""Invoice filtering engine — the rule vocabulary for invoice-scoped queries.

Companion to :mod:`app.services.quotes.quote_filters`. Exists so a workflow can
branch on the invoice that triggered it: whether it is still unpaid, how much of
it has been paid, and how far past ``due_date`` it has drifted.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select

from app.models.invoice import Invoice
from app.services._filters import apply_filter_rules

_COLUMN_MAP: dict[str, Any] = {
    "status": Invoice.status,
    "number": Invoice.number,
    "currency": Invoice.currency,
    "contact_id": Invoice.contact_id,
    "opportunity_id": Invoice.opportunity_id,
    # Money — ``amount_paid`` against ``total`` is what "partially paid" means.
    "subtotal": Invoice.subtotal,
    "tax_amount": Invoice.tax_amount,
    "discount_amount": Invoice.discount_amount,
    "total": Invoice.total,
    "amount_paid": Invoice.amount_paid,
    # Lifecycle dates — ``due_date`` is the anchor an overdue chase counts from.
    "issue_date": Invoice.issue_date,
    "due_date": Invoice.due_date,
    "sent_at": Invoice.sent_at,
    "paid_at": Invoice.paid_at,
    "last_emailed_at": Invoice.last_emailed_at,
    "payment_method": Invoice.payment_method,
    "created_at": Invoice.created_at,
    "updated_at": Invoice.updated_at,
}


def apply_invoice_filters(
    query: Select[Any],
    workspace_id: uuid.UUID,
    *,
    filter_rules: list[dict[str, Any]] | None = None,
    filter_logic: str = "and",
) -> Select[Any]:
    """Narrow ``query`` to ``workspace_id`` and apply optional JSON rules."""
    query = query.where(Invoice.workspace_id == workspace_id)
    if filter_rules:
        query = apply_filter_rules(query, filter_rules, filter_logic, _COLUMN_MAP)
    return query
