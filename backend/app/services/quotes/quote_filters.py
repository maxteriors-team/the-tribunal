"""Quote filtering engine — the rule vocabulary for quote-scoped queries.

Mirrors :mod:`app.services.campaigns.campaign_filters`: a ``_COLUMN_MAP`` naming
the fields a JSON rule may reference, delegated to
:func:`app.services._filters.apply_filter_rules` so quotes share one operator
vocabulary with contacts, campaigns and opportunities.

The immediate consumer is workflow branching. A revival sequence parked in a
30-day wait has to ask "is *this* quote still unsold?" when it wakes, and the
fields below are exactly what that question is made of: ``status`` (settled or
not), ``total`` (high-value copy vs routine), ``issue_date`` / ``sent_at`` (the
anchor price validity is measured from), and ``approved_at`` / ``declined_at``
(the moment it stopped being revivable).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select

from app.models.quote import Quote
from app.services._filters import apply_filter_rules

_COLUMN_MAP: dict[str, Any] = {
    "status": Quote.status,
    "total": Quote.total,
    "subtotal": Quote.subtotal,
    "currency": Quote.currency,
    "number": Quote.number,
    "title": Quote.title,
    "contact_id": Quote.contact_id,
    "opportunity_id": Quote.opportunity_id,
    "assigned_user_id": Quote.assigned_user_id,
    "lighting_project_id": Quote.lighting_project_id,
    "service_location_id": Quote.service_location_id,
    "primary_service": Quote.primary_service,
    "is_onsite_upsell": Quote.is_onsite_upsell,
    # Lifecycle dates — the anchors a follow-up ladder counts from.
    "issue_date": Quote.issue_date,
    "expiry_date": Quote.expiry_date,
    "sent_at": Quote.sent_at,
    "approved_at": Quote.approved_at,
    "declined_at": Quote.declined_at,
    "first_viewed_at": Quote.first_viewed_at,
    "last_viewed_at": Quote.last_viewed_at,
    "view_count": Quote.view_count,
    # Deposit + conversion state.
    "deposit_paid_at": Quote.deposit_paid_at,
    "converted_job_id": Quote.converted_job_id,
    "converted_invoice_id": Quote.converted_invoice_id,
    "created_at": Quote.created_at,
    "updated_at": Quote.updated_at,
}


def apply_quote_filters(
    query: Select[Any],
    workspace_id: uuid.UUID,
    *,
    filter_rules: list[dict[str, Any]] | None = None,
    filter_logic: str = "and",
) -> Select[Any]:
    """Narrow ``query`` to ``workspace_id`` and apply optional JSON rules."""
    query = query.where(Quote.workspace_id == workspace_id)
    if filter_rules:
        query = apply_filter_rules(query, filter_rules, filter_logic, _COLUMN_MAP)
    return query
