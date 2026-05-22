"""Pydantic schemas for lead prospects and enrichment results.

A :class:`~app.models.lead_prospect.LeadProspect` is a partial-identity lead
candidate. The :class:`LeadProspectCreate` validator enforces that **at least
one** of phone / email / website / owner-name is present — but it does not
require all of them — so phone-only, email-only, website-only, and
owner-name-only prospects are all accepted.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.lead_prospect import (
    EnrichmentProvider,
    EnrichmentResultStatus,
    ProspectIdentityKind,
    ProspectStatus,
)

# --- LeadProspect ---------------------------------------------------------


class LeadProspectCreate(BaseModel):
    """Request to create a lead prospect.

    At least one of the four identifier facets must be provided:
    ``phone_number``, ``email``, ``website_url``, or
    ``full_name`` / (``first_name`` + ``last_name``).
    """

    mission_id: uuid.UUID | None = None
    discovery_job_id: uuid.UUID | None = None
    identity_kind: ProspectIdentityKind = ProspectIdentityKind.MULTI

    # Personal identity (all nullable)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    full_name: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)

    # Channels
    email: EmailStr | None = None
    phone_number: str | None = Field(default=None, max_length=50)

    # Business / web
    company_name: str | None = Field(default=None, max_length=255)
    website_url: str | None = Field(default=None, max_length=1024)
    website_host: str | None = Field(default=None, max_length=255)
    linkedin_url: str | None = Field(default=None, max_length=500)

    # Location
    country_code: str | None = Field(default=None, max_length=2)
    region: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    location_label: str | None = Field(default=None, max_length=255)

    # Source provenance
    source_type: str | None = Field(default=None, max_length=50)
    source_external_id: str | None = Field(default=None, max_length=255)
    source_query: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)

    # Scoring + status
    dedupe_key: str | None = Field(default=None, max_length=64)
    lead_score: int = Field(default=0, ge=0)
    qualification_score: int = Field(default=0, ge=0)
    status: ProspectStatus = ProspectStatus.NEW

    @model_validator(mode="after")
    def _require_at_least_one_identifier(self) -> "LeadProspectCreate":
        """Reject prospects with no identifier at all."""
        has_phone = bool(self.phone_number)
        has_email = bool(self.email)
        has_website = bool(self.website_url or self.website_host)
        has_owner_name = bool(self.full_name or self.first_name or self.last_name)
        if not (has_phone or has_email or has_website or has_owner_name):
            raise ValueError("at least one identifier required")
        return self


class LeadProspectUpdate(BaseModel):
    """Partial update for a lead prospect."""

    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    full_name: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone_number: str | None = Field(default=None, max_length=50)
    company_name: str | None = Field(default=None, max_length=255)
    website_url: str | None = Field(default=None, max_length=1024)
    website_host: str | None = Field(default=None, max_length=255)
    linkedin_url: str | None = Field(default=None, max_length=500)
    country_code: str | None = Field(default=None, max_length=2)
    region: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    location_label: str | None = Field(default=None, max_length=255)
    provenance: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] | None = None
    lead_score: int | None = Field(default=None, ge=0)
    qualification_score: int | None = Field(default=None, ge=0)
    status: ProspectStatus | None = None
    suppression_reason: str | None = Field(default=None, max_length=255)


class LeadProspectResponse(BaseModel):
    """Response for a lead prospect (decrypted PII fields included)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    mission_id: uuid.UUID | None
    discovery_job_id: uuid.UUID | None
    contact_id: int | None
    identity_kind: ProspectIdentityKind

    first_name: str | None
    last_name: str | None
    full_name: str | None
    title: str | None

    email: str | None
    phone_number: str | None

    company_name: str | None
    website_url: str | None
    website_host: str | None
    linkedin_url: str | None

    country_code: str | None
    region: str | None
    city: str | None
    location_label: str | None

    source_type: str | None
    source_external_id: str | None
    source_query: str | None
    provenance: dict[str, Any]
    evidence: list[dict[str, Any]]

    dedupe_key: str | None
    lead_score: int
    qualification_score: int
    status: ProspectStatus
    suppression_reason: str | None

    enrichment_attempts: int
    last_enriched_at: datetime | None
    last_contacted_at: datetime | None
    last_replied_at: datetime | None
    last_failed_at: datetime | None
    reply_count: int
    bounce_count: int

    discovered_at: datetime
    promoted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaginatedLeadProspects(BaseModel):
    """Paginated prospect list."""

    items: list[LeadProspectResponse]
    total: int
    page: int
    page_size: int
    pages: int


# --- LeadEnrichmentResult -------------------------------------------------


class LeadEnrichmentResultCreate(BaseModel):
    """Request to append a new enrichment result row."""

    prospect_id: uuid.UUID
    mission_id: uuid.UUID | None = None
    provider: EnrichmentProvider
    status: EnrichmentResultStatus
    request_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | None = None
    extracted: dict[str, Any] = Field(default_factory=dict)
    score_delta: int = 0
    cost_cents: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    error_message: str | None = None


class LeadEnrichmentResultResponse(BaseModel):
    """Response for a single enrichment result."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    prospect_id: uuid.UUID
    mission_id: uuid.UUID | None
    provider: EnrichmentProvider
    status: EnrichmentResultStatus
    request_payload: dict[str, Any] | None
    response_payload: dict[str, Any] | None
    extracted: dict[str, Any]
    score_delta: int
    cost_cents: int | None
    duration_ms: int | None
    error_message: str | None
    created_at: datetime
