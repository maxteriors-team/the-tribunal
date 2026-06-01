"""Opportunity filtering engine - shared by opportunities API and future segmentation."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select

from app.db.scope import apply_workspace_scope
from app.models.opportunity import Opportunity
from app.services._filters import FilterSpec, apply_resource_filters, contains_filter

# Column map for the JSON-rule engine. Mirrors the simple kwargs below
# plus a few additional fields useful for rule-based filtering.
_COLUMN_MAP: dict[str, Any] = {
    "pipeline_id": Opportunity.pipeline_id,
    "stage_id": Opportunity.stage_id,
    "owner_id": Opportunity.assigned_user_id,
    "assigned_user_id": Opportunity.assigned_user_id,
    "status": Opportunity.status,
    "is_active": Opportunity.is_active,
    "source": Opportunity.source,
    "name": Opportunity.name,
    "amount": Opportunity.amount,
    "probability": Opportunity.probability,
    "expected_close_date": Opportunity.expected_close_date,
    "closed_date": Opportunity.closed_date,
    "created_at": Opportunity.created_at,
}

_SIMPLE_FILTER_SPECS: tuple[FilterSpec, ...] = (
    FilterSpec("pipeline_id", Opportunity.pipeline_id),
    FilterSpec("stage_id", Opportunity.stage_id),
    FilterSpec("owner_id", Opportunity.assigned_user_id),
    FilterSpec("status", Opportunity.status),
    FilterSpec("is_active", Opportunity.is_active),
    FilterSpec("source", Opportunity.source),
    FilterSpec("search", condition=contains_filter(Opportunity.name)),
    FilterSpec("value_min", Opportunity.amount, "gte"),
    FilterSpec("value_max", Opportunity.amount, "lte"),
    FilterSpec("probability_min", Opportunity.probability, "gte"),
    FilterSpec("probability_max", Opportunity.probability, "lte"),
    FilterSpec("created_after", Opportunity.created_at, "gte"),
    FilterSpec("created_before", Opportunity.created_at, "lte"),
)


def apply_opportunity_filters(  # noqa: PLR0912
    query: Select[Any],
    workspace_id: uuid.UUID,
    *,
    pipeline_id: uuid.UUID | None = None,
    stage_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    status: str | None = None,
    is_active: bool | None = None,
    source: str | None = None,
    search: str | None = None,
    value_min: Decimal | float | None = None,
    value_max: Decimal | float | None = None,
    probability_min: int | None = None,
    probability_max: int | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    # Complex filter definition (JSON)
    filter_rules: list[dict[str, Any]] | None = None,
    filter_logic: str = "and",
) -> Select[Any]:
    """Apply opportunity filters to a SQLAlchemy query.

    Single source of truth for opportunity filtering. Callers pass a base
    ``select(Opportunity)`` and receive a narrowed query. Callers may
    additionally pass a ``filter_rules`` / ``filter_logic`` pair for
    rule-based filtering (matching the shape used by contact filters).
    """
    query = apply_workspace_scope(query, Opportunity, workspace_id)
    return apply_resource_filters(
        query,
        simple_specs=_SIMPLE_FILTER_SPECS,
        values={
            "pipeline_id": pipeline_id,
            "stage_id": stage_id,
            "owner_id": owner_id,
            "status": status,
            "is_active": is_active,
            "source": source,
            "search": search,
            "value_min": value_min,
            "value_max": value_max,
            "probability_min": probability_min,
            "probability_max": probability_max,
            "created_after": created_after,
            "created_before": created_before,
        },
        filter_rules=filter_rules,
        filter_logic=filter_logic,
        column_map=_COLUMN_MAP,
    )
