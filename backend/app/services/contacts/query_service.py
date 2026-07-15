"""Contact query service for list and select-all endpoints."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.pagination import PaginationResult
from app.db.scope import apply_workspace_scope
from app.models.contact import Contact
from app.schemas.contact import ContactWithConversationResponse
from app.schemas.tag import TagResponse
from app.services.contacts.contact_repository import (
    list_contact_ids as repo_list_contact_ids,
)
from app.services.contacts.contact_repository import (
    list_contacts_paginated,
)
from app.services.contacts.exceptions import ContactValidationError

logger = structlog.get_logger()


def _pct_change(curr: int, prev: int) -> str:
    """Format a period-over-period percentage change for the stat cards.

    Returns a preformatted string (``"+N%"`` / ``"-N%"`` / ``"+0%"``) so the
    frontend ``isTrendUp`` helper renders the trend badge without reparsing.
    When the prior window is empty but the current one isn't, treat it as full
    growth (``"+100%"``); when both windows are empty there is no change
    (``"+0%"``).
    """
    if prev == 0:
        return "+100%" if curr > 0 else "+0%"
    pct = int(round((curr - prev) / prev * 100))
    return f"{'+' if pct >= 0 else '-'}{abs(pct)}%"


@dataclass(slots=True, frozen=True)
class ParsedContactFilters:
    """Normalized filters accepted by repository query functions."""

    tags: list[uuid.UUID] | None
    tags_match: str
    lead_score_min: int | None
    lead_score_max: int | None
    is_qualified: bool | None
    source: str | None
    company_name: str | None
    created_after: datetime | None
    created_before: datetime | None
    enrichment_status: str | None
    filter_rules: list[dict[str, Any]] | None
    filter_logic: str

    def as_kwargs(self) -> dict[str, Any]:
        """Return repository-compatible keyword arguments."""
        return {
            "tags": self.tags,
            "tags_match": self.tags_match,
            "lead_score_min": self.lead_score_min,
            "lead_score_max": self.lead_score_max,
            "is_qualified": self.is_qualified,
            "source": self.source,
            "company_name": self.company_name,
            "created_after": self.created_after,
            "created_before": self.created_before,
            "enrichment_status": self.enrichment_status,
            "filter_rules": self.filter_rules,
            "filter_logic": self.filter_logic,
        }


def parse_contact_filters(
    *,
    tags: str | None = None,
    tags_match: str = "any",
    lead_score_min: int | None = None,
    lead_score_max: int | None = None,
    is_qualified: bool | None = None,
    source: str | None = None,
    company_name: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    enrichment_status: str | None = None,
    filters: str | None = None,
) -> ParsedContactFilters:
    """Parse contact filter query parameters into repository arguments."""
    tag_uuids: list[uuid.UUID] | None = None
    if tags:
        tag_uuids = [uuid.UUID(tag.strip()) for tag in tags.split(",") if tag.strip()]

    filter_rules: list[dict[str, Any]] | None = None
    filter_logic = "and"
    if filters:
        try:
            parsed = json.loads(filters)
            filter_rules = parsed.get("rules")
            filter_logic = parsed.get("logic", "and")
        except (json.JSONDecodeError, AttributeError) as exc:
            raise ContactValidationError("Invalid filters JSON") from exc

    return ParsedContactFilters(
        tags=tag_uuids,
        tags_match=tags_match,
        lead_score_min=lead_score_min,
        lead_score_max=lead_score_max,
        is_qualified=is_qualified,
        source=source,
        company_name=company_name,
        created_after=created_after,
        created_before=created_before,
        enrichment_status=enrichment_status,
        filter_rules=filter_rules,
        filter_logic=filter_logic,
    )


class ContactQueryService:
    """High-level contact query operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(service="contact_query")

    async def list_contacts(
        self,
        *,
        workspace_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        status_filter: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        tags: str | list[uuid.UUID] | None = None,
        tags_match: str = "any",
        lead_score_min: int | None = None,
        lead_score_max: int | None = None,
        is_qualified: bool | None = None,
        source: str | None = None,
        company_name: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        enrichment_status: str | None = None,
        filter_rules: list[dict[str, Any]] | None = None,
        filter_logic: str = "and",
        filters: str | None = None,
    ) -> dict[str, Any]:
        """List contacts in a workspace with pagination and filters."""
        parsed_filters = self._normalize_filters(
            tags=tags,
            tags_match=tags_match,
            lead_score_min=lead_score_min,
            lead_score_max=lead_score_max,
            is_qualified=is_qualified,
            source=source,
            company_name=company_name,
            created_after=created_after,
            created_before=created_before,
            enrichment_status=enrichment_status,
            filter_rules=filter_rules,
            filter_logic=filter_logic,
            filters=filters,
        )

        rows, total = await list_contacts_paginated(
            workspace_id=workspace_id,
            db=self.db,
            page=page,
            page_size=page_size,
            status_filter=status_filter,
            search=search,
            sort_by=sort_by,
            **parsed_filters.as_kwargs(),
        )

        items = []
        for row in rows:
            contact = row[0]
            contact_data = ContactWithConversationResponse.model_validate(contact)
            contact_data.unread_count = row[1] or 0
            contact_data.last_message_at = row[2]
            contact_data.last_message_direction = row[3]
            if hasattr(contact, "contact_tags") and contact.contact_tags:
                contact_data.tag_objects = [
                    TagResponse.model_validate(contact_tag.tag)
                    for contact_tag in contact.contact_tags
                    if contact_tag.tag is not None
                ]
            items.append(contact_data)

        return PaginationResult(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size if total > 0 else 1,
        ).to_dict()

    async def get_stats(self, *, workspace_id: uuid.UUID) -> dict[str, Any]:
        """Compute workspace-scoped contact metrics for the stat cards.

        Mirrors the Jobber Clients dashboard: "new leads" and "new clients"
        over the trailing 30 days (with a period-over-period change vs the
        prior 30-day window) plus year-to-date new clients. "Client" maps to
        our ``converted`` status. All windows are UTC and workspace-scoped.
        """
        now = datetime.now(UTC)
        window_30d = now - timedelta(days=30)
        window_60d = now - timedelta(days=60)
        year_start = datetime(now.year, 1, 1, tzinfo=UTC)

        async def _count(*criteria: Any) -> int:
            query = apply_workspace_scope(
                select(func.count()).select_from(Contact), Contact, workspace_id
            )
            if criteria:
                query = query.where(*criteria)
            result = await self.db.execute(query)
            return result.scalar_one() or 0

        new_leads_30d = await _count(Contact.created_at >= window_30d)
        new_leads_prev = await _count(
            Contact.created_at >= window_60d,
            Contact.created_at < window_30d,
        )
        new_clients_30d = await _count(
            Contact.status == "converted",
            Contact.created_at >= window_30d,
        )
        new_clients_prev = await _count(
            Contact.status == "converted",
            Contact.created_at >= window_60d,
            Contact.created_at < window_30d,
        )
        total_new_clients_ytd = await _count(
            Contact.status == "converted",
            Contact.created_at >= year_start,
        )

        return {
            "new_leads_30d": new_leads_30d,
            "new_leads_change": _pct_change(new_leads_30d, new_leads_prev),
            "new_clients_30d": new_clients_30d,
            "new_clients_change": _pct_change(new_clients_30d, new_clients_prev),
            "total_new_clients_ytd": total_new_clients_ytd,
        }

    async def list_contact_ids(
        self,
        *,
        workspace_id: uuid.UUID,
        status_filter: str | None = None,
        search: str | None = None,
        tags: str | list[uuid.UUID] | None = None,
        tags_match: str = "any",
        lead_score_min: int | None = None,
        lead_score_max: int | None = None,
        is_qualified: bool | None = None,
        source: str | None = None,
        company_name: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        enrichment_status: str | None = None,
        filter_rules: list[dict[str, Any]] | None = None,
        filter_logic: str = "and",
        filters: str | None = None,
    ) -> dict[str, Any]:
        """Return every contact ID matching the supplied filters."""
        parsed_filters = self._normalize_filters(
            tags=tags,
            tags_match=tags_match,
            lead_score_min=lead_score_min,
            lead_score_max=lead_score_max,
            is_qualified=is_qualified,
            source=source,
            company_name=company_name,
            created_after=created_after,
            created_before=created_before,
            enrichment_status=enrichment_status,
            filter_rules=filter_rules,
            filter_logic=filter_logic,
            filters=filters,
        )

        ids, total = await repo_list_contact_ids(
            workspace_id=workspace_id,
            db=self.db,
            status_filter=status_filter,
            search=search,
            **parsed_filters.as_kwargs(),
        )

        return {"ids": ids, "total": total}

    def _normalize_filters(
        self,
        *,
        tags: str | list[uuid.UUID] | None,
        tags_match: str,
        lead_score_min: int | None,
        lead_score_max: int | None,
        is_qualified: bool | None,
        source: str | None,
        company_name: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
        enrichment_status: str | None,
        filter_rules: list[dict[str, Any]] | None,
        filter_logic: str,
        filters: str | None,
    ) -> ParsedContactFilters:
        """Accept either route-level strings or already-normalized service arguments."""
        if isinstance(tags, str):
            return parse_contact_filters(
                tags=tags,
                tags_match=tags_match,
                lead_score_min=lead_score_min,
                lead_score_max=lead_score_max,
                is_qualified=is_qualified,
                source=source,
                company_name=company_name,
                created_after=created_after,
                created_before=created_before,
                enrichment_status=enrichment_status,
                filters=filters,
            )

        if filters is not None:
            parsed_json_filters = parse_contact_filters(
                tags=None,
                tags_match=tags_match,
                lead_score_min=lead_score_min,
                lead_score_max=lead_score_max,
                is_qualified=is_qualified,
                source=source,
                company_name=company_name,
                created_after=created_after,
                created_before=created_before,
                enrichment_status=enrichment_status,
                filters=filters,
            )
            return ParsedContactFilters(
                tags=tags,
                tags_match=parsed_json_filters.tags_match,
                lead_score_min=parsed_json_filters.lead_score_min,
                lead_score_max=parsed_json_filters.lead_score_max,
                is_qualified=parsed_json_filters.is_qualified,
                source=parsed_json_filters.source,
                company_name=parsed_json_filters.company_name,
                created_after=parsed_json_filters.created_after,
                created_before=parsed_json_filters.created_before,
                enrichment_status=parsed_json_filters.enrichment_status,
                filter_rules=parsed_json_filters.filter_rules,
                filter_logic=parsed_json_filters.filter_logic,
            )

        return ParsedContactFilters(
            tags=tags,
            tags_match=tags_match,
            lead_score_min=lead_score_min,
            lead_score_max=lead_score_max,
            is_qualified=is_qualified,
            source=source,
            company_name=company_name,
            created_after=created_after,
            created_before=created_before,
            enrichment_status=enrichment_status,
            filter_rules=filter_rules,
            filter_logic=filter_logic,
        )
