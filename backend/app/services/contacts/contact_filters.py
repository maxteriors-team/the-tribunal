"""Contact filtering engine - shared by contacts API and segment resolution."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.sql.elements import ColumnElement

from app.models.contact import Contact
from app.models.tag import ContactTag
from app.services._filters import (
    FilterSpec,
    apply_filter_specs,
    apply_resource_filters,
    contains_filter,
    range_filter_specs,
    search_filter,
)

# Column map for the JSON-rule engine. Exposed at module level so other
# code (e.g. tests) can introspect the supported fields.
_COLUMN_MAP: dict[str, Any] = {
    "status": Contact.status,
    "lead_score": Contact.lead_score,
    "is_qualified": Contact.is_qualified,
    "source": Contact.source,
    "company_name": Contact.company_name,
    "created_at": Contact.created_at,
    "enrichment_status": Contact.enrichment_status,
    "email": Contact.email,
    "first_name": Contact.first_name,
    "last_name": Contact.last_name,
}

_BASE_LIST_FILTER_SPECS: tuple[FilterSpec, ...] = (
    FilterSpec("status_filter", Contact.status),
    FilterSpec(
        "search",
        condition=search_filter(
            Contact.first_name,
            Contact.last_name,
            Contact.email,
            Contact.phone_number,
            Contact.company_name,
        ),
    ),
)
_ADVANCED_FILTER_SPECS: tuple[FilterSpec, ...] = (
    FilterSpec("tags", condition=lambda value: _build_simple_tag_condition(value[0], value[1])),
    *range_filter_specs("lead_score", Contact.lead_score),
    FilterSpec("is_qualified", Contact.is_qualified),
    FilterSpec("source", Contact.source),
    FilterSpec("company_name", condition=contains_filter(Contact.company_name)),
    FilterSpec("created_after", Contact.created_at, "gte"),
    FilterSpec("created_before", Contact.created_at, "lte"),
    FilterSpec("enrichment_status", Contact.enrichment_status),
)


def apply_contact_list_filters(
    query: Select[Any],
    *,
    status_filter: str | None = None,
    search: str | None = None,
) -> Select[Any]:
    """Apply common contact-list filters shared by list and select-all queries."""
    return apply_filter_specs(
        query,
        _BASE_LIST_FILTER_SPECS,
        {
            "status_filter": status_filter,
            "search": search,
        },
    )


def apply_contact_filters(
    query: Select[Any],
    workspace_id: uuid.UUID,
    *,
    # Simple filters (query params)
    tags: list[uuid.UUID] | None = None,
    tags_match: str = "any",  # "any", "all", "none"
    lead_score_min: int | None = None,
    lead_score_max: int | None = None,
    is_qualified: bool | None = None,
    source: str | None = None,
    company_name: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    enrichment_status: str | None = None,
    # Complex filter definition (JSON)
    filter_rules: list[dict[str, Any]] | None = None,
    filter_logic: str = "and",
) -> Select[Any]:
    """Apply contact filters to a SQLAlchemy query.

    This function is the single source of truth for all contact filtering.
    Used by both the contacts API and segment resolution.
    """
    return apply_resource_filters(
        query,
        simple_specs=_ADVANCED_FILTER_SPECS,
        values={
            "tags": (tags, tags_match) if tags else None,
            "lead_score_min": lead_score_min,
            "lead_score_max": lead_score_max,
            "is_qualified": is_qualified,
            "source": source,
            "company_name": company_name,
            "created_after": created_after,
            "created_before": created_before,
            "enrichment_status": enrichment_status,
        },
        filter_rules=filter_rules,
        filter_logic=filter_logic,
        column_map=_COLUMN_MAP,
        extra_resolver=_resolve_contact_extra,
    )


def _build_simple_tag_condition(
    tag_ids: list[uuid.UUID],
    match_mode: str,
) -> ColumnElement[bool] | None:
    """Build a tag condition for query-parameter filters."""
    if not tag_ids:
        return None
    operator = {
        "all": "has_all",
        "none": "has_none",
    }.get(match_mode, "has_any")
    return _build_tag_condition(operator, tag_ids)


def _resolve_contact_extra(field: str, operator: str, value: Any) -> ColumnElement[bool] | None:
    """Resolve non-column contact filter fields (currently only ``tags``)."""
    if field == "tags":
        return _build_tag_condition(operator, value)
    return None


def _build_tag_condition(operator: str, value: Any) -> ColumnElement[bool] | None:
    """Build a tag-based filter condition."""
    if not isinstance(value, list) or not value:
        return None

    tag_ids = [uuid.UUID(v) if isinstance(v, str) else v for v in value]

    if operator == "has_any":
        subq = select(ContactTag.contact_id).where(ContactTag.tag_id.in_(tag_ids)).distinct()
        return Contact.id.in_(subq)
    elif operator == "has_all":
        subq = (
            select(ContactTag.contact_id)
            .where(ContactTag.tag_id.in_(tag_ids))
            .group_by(ContactTag.contact_id)
            .having(func.count(func.distinct(ContactTag.tag_id)) == len(tag_ids))
        )
        return Contact.id.in_(subq)
    elif operator == "has_none":
        subq = select(ContactTag.contact_id).where(ContactTag.tag_id.in_(tag_ids)).distinct()
        return Contact.id.notin_(subq)

    return None
