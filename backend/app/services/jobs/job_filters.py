"""Job filtering engine — the rule vocabulary for job-scoped queries.

Companion to :mod:`app.services.quotes.quote_filters`. Exists so a workflow can
branch on the job that triggered it — whether it actually completed, which crew
ran it, and whether it came from a lighting project — rather than on whatever
the customer's contact record happens to say.

``status`` is a :class:`~app.models.field_service.JobStatus` ``StrEnum``, so
rules may compare against the plain strings (``"completed"``, ``"cancelled"``)
that a workflow definition stores in JSONB.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select

from app.models.field_service import Job
from app.services._filters import apply_filter_rules

_COLUMN_MAP: dict[str, Any] = {
    "status": Job.status,
    "title": Job.title,
    "contact_id": Job.contact_id,
    "crew_id": Job.crew_id,
    "business_location_id": Job.business_location_id,
    "service_location_id": Job.service_location_id,
    "invoice_id": Job.invoice_id,
    # Provenance — ``lighting_project_id`` is what distinguishes a landscape
    # system install from a service call, repair or takedown.
    "lighting_project_id": Job.lighting_project_id,
    "source_quote_id": Job.source_quote_id,
    "source_quote_phase": Job.source_quote_phase,
    "recurring_template_id": Job.recurring_template_id,
    # Scheduling window — the anchors a reminder or follow-up counts from.
    "scheduled_start": Job.scheduled_start,
    "scheduled_end": Job.scheduled_end,
    "created_at": Job.created_at,
    "updated_at": Job.updated_at,
}


def apply_job_filters(
    query: Select[Any],
    workspace_id: uuid.UUID,
    *,
    filter_rules: list[dict[str, Any]] | None = None,
    filter_logic: str = "and",
) -> Select[Any]:
    """Narrow ``query`` to ``workspace_id`` and apply optional JSON rules."""
    query = query.where(Job.workspace_id == workspace_id)
    if filter_rules:
        query = apply_filter_rules(query, filter_rules, filter_logic, _COLUMN_MAP)
    return query
