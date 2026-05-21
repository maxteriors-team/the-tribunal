"""Pydantic schemas for the Outbound Mission API.

A mission groups a discovery + enrichment + outreach run under one objective
(book_call, qualify, nurture, demo, custom). The schemas mirror the
:class:`~app.models.outbound_mission.OutboundMission` ORM model.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.outbound_mission import MissionStatus


class OutboundMissionCreate(BaseModel):
    """Request to create an outbound mission."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    objective: str = Field(default="book_call", max_length=50)
    offer_id: uuid.UUID | None = None
    default_agent_id: uuid.UUID | None = None
    default_sequence_id: uuid.UUID | None = None
    target_audience: dict[str, Any] = Field(default_factory=dict)
    discovery_config: dict[str, Any] = Field(default_factory=dict)
    enrichment_config: dict[str, Any] = Field(default_factory=dict)
    sequence_config: dict[str, Any] = Field(default_factory=dict)
    default_from_phone_number: str | None = Field(default=None, max_length=50)
    default_from_email: str | None = Field(default=None, max_length=320)
    daily_prospect_cap: int = Field(default=100, ge=0)
    daily_outreach_cap: int = Field(default=50, ge=0)
    timezone: str = Field(default="America/New_York", max_length=50)


class OutboundMissionUpdate(BaseModel):
    """Partial update for an outbound mission."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    objective: str | None = Field(default=None, max_length=50)
    status: MissionStatus | None = None
    offer_id: uuid.UUID | None = None
    default_agent_id: uuid.UUID | None = None
    default_sequence_id: uuid.UUID | None = None
    target_audience: dict[str, Any] | None = None
    discovery_config: dict[str, Any] | None = None
    enrichment_config: dict[str, Any] | None = None
    sequence_config: dict[str, Any] | None = None
    default_from_phone_number: str | None = Field(default=None, max_length=50)
    default_from_email: str | None = Field(default=None, max_length=320)
    daily_prospect_cap: int | None = Field(default=None, ge=0)
    daily_outreach_cap: int | None = Field(default=None, ge=0)
    timezone: str | None = Field(default=None, max_length=50)


class OutboundMissionResponse(BaseModel):
    """Response for an outbound mission."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    created_by_id: int | None
    offer_id: uuid.UUID | None
    default_agent_id: uuid.UUID | None
    default_sequence_id: uuid.UUID | None
    name: str
    description: str | None
    objective: str
    status: MissionStatus
    target_audience: dict[str, Any]
    discovery_config: dict[str, Any]
    enrichment_config: dict[str, Any]
    sequence_config: dict[str, Any]
    default_from_phone_number: str | None
    default_from_email: str | None
    daily_prospect_cap: int
    daily_outreach_cap: int
    timezone: str
    total_prospects_discovered: int
    total_prospects_enriched: int
    total_prospects_contacted: int
    total_prospects_replied: int
    total_prospects_qualified: int
    total_contacts_created: int
    total_appointments_booked: int
    started_at: datetime | None
    paused_at: datetime | None
    completed_at: datetime | None
    archived_at: datetime | None
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OutboundMissionStatsResponse(BaseModel):
    """Aggregate stats for an outbound mission."""

    model_config = ConfigDict(from_attributes=True)

    mission_id: uuid.UUID
    total_prospects_discovered: int
    total_prospects_enriched: int
    total_prospects_contacted: int
    total_prospects_replied: int
    total_prospects_qualified: int
    total_contacts_created: int
    total_appointments_booked: int
    reply_rate: float
    qualification_rate: float
    booking_rate: float


class PaginatedOutboundMissions(BaseModel):
    """Paginated mission list."""

    items: list[OutboundMissionResponse]
    total: int
    page: int
    page_size: int
