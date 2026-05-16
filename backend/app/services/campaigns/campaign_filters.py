"""Campaign filtering engine - shared query builder for campaign listing."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select

from app.models.campaign import Campaign
from app.services._filters import apply_filter_rules

# Column map for the JSON-rule engine. Mirrors the simple kwargs below
# plus a few extras that are useful when callers want to compose richer
# expressions through ``filter_rules`` / ``filter_logic``.
_COLUMN_MAP: dict[str, Any] = {
    "status": Campaign.status,
    "campaign_type": Campaign.campaign_type,
    "agent_id": Campaign.agent_id,
    "offer_id": Campaign.offer_id,
    "name": Campaign.name,
    "created_at": Campaign.created_at,
    "started_at": Campaign.started_at,
    "completed_at": Campaign.completed_at,
    "messages_sent": Campaign.messages_sent,
    "contacts_qualified": Campaign.contacts_qualified,
    "appointments_booked": Campaign.appointments_booked,
}


def apply_campaign_filters(
    query: Select[Any],
    workspace_id: uuid.UUID,
    *,
    status: str | None = None,
    campaign_type: str | None = None,
    agent_id: uuid.UUID | None = None,
    offer_id: uuid.UUID | None = None,
    name: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    # Complex filter definition (JSON)
    filter_rules: list[dict[str, Any]] | None = None,
    filter_logic: str = "and",
) -> Select[Any]:
    """Apply campaign filters to a SQLAlchemy query.

    Single source of truth for campaign list filtering. Always scopes the
    query to ``workspace_id``. Callers may pass either the simple keyword
    arguments below or a ``filter_rules`` / ``filter_logic`` pair for
    rule-based filtering (matching the shape used by contact filters).
    """
    query = query.where(Campaign.workspace_id == workspace_id)

    if status:
        query = query.where(Campaign.status == status)
    if campaign_type:
        query = query.where(Campaign.campaign_type == campaign_type)
    if agent_id is not None:
        query = query.where(Campaign.agent_id == agent_id)
    if offer_id is not None:
        query = query.where(Campaign.offer_id == offer_id)

    if name:
        query = query.where(Campaign.name.ilike(f"%{name}%"))

    if created_after:
        query = query.where(Campaign.created_at >= created_after)
    if created_before:
        query = query.where(Campaign.created_at <= created_before)
    if started_after:
        query = query.where(Campaign.started_at >= started_after)
    if started_before:
        query = query.where(Campaign.started_at <= started_before)

    if filter_rules:
        query = apply_filter_rules(query, filter_rules, filter_logic, _COLUMN_MAP)

    return query
