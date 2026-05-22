"""Pydantic schemas for lead discovery jobs."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.lead_discovery_job import DiscoveryJobStatus, DiscoverySourceType


class LeadDiscoveryJobCreate(BaseModel):
    """Request to enqueue a new discovery job."""

    mission_id: uuid.UUID | None = None
    source_type: DiscoverySourceType
    source_label: str | None = Field(default=None, max_length=255)
    query: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    requested_count: int = Field(default=0, ge=0)


class LeadDiscoveryJobUpdate(BaseModel):
    """Partial update for a discovery job (status / counters / errors)."""

    status: DiscoveryJobStatus | None = None
    requested_count: int | None = Field(default=None, ge=0)
    discovered_count: int | None = Field(default=None, ge=0)
    duplicate_count: int | None = Field(default=None, ge=0)
    invalid_count: int | None = Field(default=None, ge=0)
    last_error: str | None = None
    error_count: int | None = Field(default=None, ge=0)


class LeadDiscoveryJobResponse(BaseModel):
    """Response for a discovery job."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    mission_id: uuid.UUID | None
    requested_by_id: int | None
    source_type: DiscoverySourceType
    source_label: str | None
    query: str | None
    params: dict[str, Any]
    status: DiscoveryJobStatus
    requested_count: int
    discovered_count: int
    duplicate_count: int
    invalid_count: int
    started_at: datetime | None
    completed_at: datetime | None
    last_error: str | None
    error_count: int
    created_at: datetime
    updated_at: datetime


class PaginatedLeadDiscoveryJobs(BaseModel):
    """Paginated discovery job list."""

    items: list[LeadDiscoveryJobResponse]
    total: int
    page: int
    page_size: int
    pages: int
