"""Opportunity schemas."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OpportunityStatus = Literal["open", "won", "lost", "abandoned"]


# Pipeline schemas
class PipelineStageBase(BaseModel):
    """Base pipeline stage schema."""

    name: str
    description: str | None = None
    order: int
    probability: int = Field(ge=0, le=100)
    stage_type: str = "active"  # active, won, lost


class PipelineStageCreate(PipelineStageBase):
    """Create pipeline stage schema."""

    pass


class PipelineStageUpdate(BaseModel):
    """Update pipeline stage schema."""

    name: str | None = None
    description: str | None = None
    order: int | None = None
    probability: int | None = Field(None, ge=0, le=100)
    stage_type: str | None = None


class PipelineStageResponse(PipelineStageBase):
    """Pipeline stage response schema."""

    id: uuid.UUID
    pipeline_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PipelineBase(BaseModel):
    """Base pipeline schema."""

    name: str
    description: str | None = None


class PipelineCreate(PipelineBase):
    """Create pipeline schema."""

    pass


class PipelineUpdate(BaseModel):
    """Update pipeline schema."""

    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class PipelineResponse(PipelineBase):
    """Pipeline response schema."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
    stages: list[PipelineStageResponse] = []

    model_config = ConfigDict(from_attributes=True)


# Opportunity schemas
class OpportunityLineItemBase(BaseModel):
    """Base line item schema."""

    name: str
    description: str | None = None
    quantity: float = 1.0
    unit_price: float
    discount: float = 0.0


class OpportunityLineItemCreate(OpportunityLineItemBase):
    """Create line item schema."""

    pass


class OpportunityLineItemUpdate(BaseModel):
    """Update line item schema."""

    name: str | None = None
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    discount: float | None = None


class OpportunityLineItemResponse(OpportunityLineItemBase):
    """Line item response schema."""

    id: uuid.UUID
    opportunity_id: uuid.UUID
    total: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OpportunityActivityResponse(BaseModel):
    """Opportunity activity response schema."""

    id: uuid.UUID
    opportunity_id: uuid.UUID
    activity_type: str
    old_value: str | None = None
    new_value: str | None = None
    description: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OpportunityBase(BaseModel):
    """Base opportunity schema."""

    name: str
    description: str | None = None
    amount: float | None = None
    currency: str = "USD"
    expected_close_date: date | None = None
    source: str | None = None
    status: OpportunityStatus = "open"
    lost_reason: str | None = None


class OpportunityCreate(OpportunityBase):
    """Create opportunity schema."""

    pipeline_id: uuid.UUID
    stage_id: uuid.UUID | None = None
    primary_contact_id: int | None = None


class OpportunityUpdate(BaseModel):
    """Update opportunity schema."""

    name: str | None = None
    description: str | None = None
    amount: float | None = None
    currency: str | None = None
    stage_id: uuid.UUID | None = None
    expected_close_date: date | None = None
    assigned_user_id: int | None = None
    source: str | None = None
    status: OpportunityStatus | None = None
    lost_reason: str | None = None
    is_active: bool | None = None


class OpportunityResponse(OpportunityBase):
    """Opportunity response schema."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    pipeline_id: uuid.UUID
    stage_id: uuid.UUID | None = None
    primary_contact_id: int | None = None
    assigned_user_id: int | None = None
    probability: int
    status: OpportunityStatus
    lost_reason: str | None = None
    closed_date: date | None = None
    closed_by_id: int | None = None
    stage_changed_at: datetime | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    line_items: list[OpportunityLineItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class OpportunityDetailResponse(OpportunityResponse):
    """Detailed opportunity response with all related data."""

    activities: list[OpportunityActivityResponse] = []


class PaginatedOpportunities(BaseModel):
    """Paginated opportunities response."""

    items: list[OpportunityResponse]
    total: int
    page: int
    page_size: int
    pages: int
