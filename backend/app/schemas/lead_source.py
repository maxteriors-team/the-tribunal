"""Lead Source schemas."""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.lead_source import LeadSourceType

LeadSourceAction = Literal["collect", "auto_text", "auto_call", "enroll_campaign"]


class AttributionConfidenceLevel(StrEnum):
    """Human-readable confidence bucket for lead-source attribution."""

    EXACT = "exact"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class AttributionConfidenceSummary(BaseModel):
    """Rollup of how reliable the attribution is for a source ROI row."""

    average_score: float | None = Field(default=None, ge=0.0, le=1.0)
    level: AttributionConfidenceLevel = AttributionConfidenceLevel.UNKNOWN
    attributed_closed_won_jobs: int = Field(default=0, ge=0)
    total_closed_won_jobs: int = Field(default=0, ge=0)
    notes: list[str] = Field(default_factory=list)


class LeadAttributionFields(BaseModel):
    """Structured first/latest touch fields stored on contacts."""

    first_touch_lead_source_id: uuid.UUID | None = None
    first_touch_lead_source_campaign_id: uuid.UUID | None = None
    first_touch_at: datetime | None = None
    latest_touch_lead_source_id: uuid.UUID | None = None
    latest_touch_lead_source_campaign_id: uuid.UUID | None = None
    latest_touch_at: datetime | None = None
    attribution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    utm_source: str | None = Field(default=None, max_length=255)
    utm_medium: str | None = Field(default=None, max_length=255)
    utm_campaign: str | None = Field(default=None, max_length=255)
    utm_content: str | None = Field(default=None, max_length=255)
    utm_term: str | None = Field(default=None, max_length=255)
    gclid: str | None = Field(default=None, max_length=255)
    fbclid: str | None = Field(default=None, max_length=255)
    landing_page: str | None = Field(default=None, max_length=2048)
    referrer: str | None = Field(default=None, max_length=2048)


class OpportunityLeadAttributionFields(BaseModel):
    """Attribution snapshot copied onto closed-won jobs/opportunities."""

    lead_source_id: uuid.UUID | None = None
    lead_source_campaign_id: uuid.UUID | None = None
    attribution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class LeadSourceCampaignBase(BaseModel):
    """Shared lead-source campaign fields."""

    name: str = Field(..., min_length=1, max_length=255)
    platform_campaign_id: str | None = Field(default=None, max_length=255)
    platform_campaign_name: str | None = Field(default=None, max_length=255)
    utm_campaign: str | None = Field(default=None, max_length=255)
    description: str | None = None
    enabled: bool = True
    campaign_metadata: dict[str, Any] = Field(default_factory=dict)
    started_on: date | None = None
    ended_on: date | None = None

    @model_validator(mode="after")
    def validate_flight_dates(self) -> Self:
        """Ensure the optional flight end is not before the start."""
        if self.started_on and self.ended_on and self.ended_on < self.started_on:
            msg = "ended_on must be on or after started_on"
            raise ValueError(msg)
        return self


class LeadSourceCampaignCreate(LeadSourceCampaignBase):
    """Schema for creating an attribution campaign under a lead source."""

    lead_source_id: uuid.UUID


class LeadSourceCampaignUpdate(BaseModel):
    """Schema for updating an attribution campaign."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    platform_campaign_id: str | None = Field(default=None, max_length=255)
    platform_campaign_name: str | None = Field(default=None, max_length=255)
    utm_campaign: str | None = Field(default=None, max_length=255)
    description: str | None = None
    enabled: bool | None = None
    campaign_metadata: dict[str, Any] | None = None
    started_on: date | None = None
    ended_on: date | None = None

    @model_validator(mode="after")
    def validate_flight_dates(self) -> Self:
        """Validate date ranges when both ends are supplied in one update."""
        if self.started_on and self.ended_on and self.ended_on < self.started_on:
            msg = "ended_on must be on or after started_on"
            raise ValueError(msg)
        return self


class LeadSourceCampaignResponse(LeadSourceCampaignBase):
    """Schema for returning a lead-source campaign."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    lead_source_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeadSourceSpendEntryBase(BaseModel):
    """Shared fields for manual ad/source spend entries."""

    lead_source_campaign_id: uuid.UUID | None = None
    spend_starts_on: date
    spend_ends_on: date
    amount: float = Field(..., ge=0.0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    notes: str | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Store ISO currency codes uppercase for stable grouping."""
        return v.upper()

    @model_validator(mode="after")
    def validate_spend_dates(self) -> Self:
        """Ensure spend ranges are chronological."""
        if self.spend_ends_on < self.spend_starts_on:
            msg = "spend_ends_on must be on or after spend_starts_on"
            raise ValueError(msg)
        return self


class LeadSourceSpendEntryCreate(LeadSourceSpendEntryBase):
    """Schema for creating a manual ad/source spend entry."""

    lead_source_id: uuid.UUID


class LeadSourceSpendEntryUpdate(BaseModel):
    """Schema for updating a manual ad/source spend entry."""

    lead_source_id: uuid.UUID | None = None
    lead_source_campaign_id: uuid.UUID | None = None
    spend_starts_on: date | None = None
    spend_ends_on: date | None = None
    amount: float | None = Field(default=None, ge=0.0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str | None) -> str | None:
        """Store ISO currency codes uppercase for stable grouping."""
        return v.upper() if v else v

    @model_validator(mode="after")
    def validate_spend_dates(self) -> Self:
        """Validate date ranges when both ends are supplied in one update."""
        if (
            self.spend_starts_on
            and self.spend_ends_on
            and self.spend_ends_on < self.spend_starts_on
        ):
            msg = "spend_ends_on must be on or after spend_starts_on"
            raise ValueError(msg)
        return self


class LeadSourceSpendEntryResponse(LeadSourceSpendEntryBase):
    """Schema for returning a manual ad/source spend entry."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    lead_source_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UnattributedLeadResponse(BaseModel):
    """A captured lead that has no known first-touch lead source yet."""

    contact_id: int
    first_name: str
    last_name: str | None = None
    phone_number: str | None = None
    email: str | None = None
    source: str | None = None
    created_at: datetime
    suggested_source_type: LeadSourceType | None = None
    suggested_lead_source_id: uuid.UUID | None = None


class AssignLeadSourceRequest(BaseModel):
    """Operator action assigning a lead source to an unattributed contact."""

    lead_source_id: uuid.UUID
    lead_source_campaign_id: uuid.UUID | None = None
    source_type: LeadSourceType | None = None


class SourceROIRow(BaseModel):
    """One ranked lead-source ROI row for dashboard reporting."""

    rank: int = Field(..., ge=1)
    source_type: LeadSourceType
    source_name: str
    lead_source_id: uuid.UUID | None = None
    spend: float = Field(default=0.0, ge=0.0)
    closed_won_jobs: int = Field(default=0, ge=0)
    closed_won_revenue: float = Field(default=0.0, ge=0.0)
    cost_per_closed_won_job: float | None = Field(default=None, ge=0.0)
    revenue_per_closed_won_job: float | None = Field(default=None, ge=0.0)
    roi_multiple: float | None = Field(default=None, ge=0.0)
    net_revenue: float = 0.0
    currency: str = Field(default="USD", min_length=3, max_length=3)
    attribution_confidence: AttributionConfidenceSummary = Field(
        default_factory=AttributionConfidenceSummary
    )
    is_winner: bool = False

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Return dashboard currency codes in uppercase."""
        return v.upper()


class LeadSourceWinnerSummary(BaseModel):
    """Summary card for the current winning lead source."""

    has_winner: bool = False
    source_type: LeadSourceType | None = None
    source_name: str | None = None
    lead_source_id: uuid.UUID | None = None
    rank_by: Literal["roi", "closed_won_revenue", "closed_won_jobs", "none"] = "none"
    spend: float = Field(default=0.0, ge=0.0)
    closed_won_jobs: int = Field(default=0, ge=0)
    closed_won_revenue: float = Field(default=0.0, ge=0.0)
    roi_multiple: float | None = Field(default=None, ge=0.0)
    net_revenue: float = 0.0
    currency: str = Field(default="USD", min_length=3, max_length=3)
    reason: str = "No closed-won jobs with attributed lead-source data yet."
    attribution_confidence: AttributionConfidenceSummary = Field(
        default_factory=AttributionConfidenceSummary
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Return dashboard currency codes in uppercase."""
        return v.upper()


class LeadSourceROIStats(BaseModel):
    """Dashboard payload for ranking lead sources by spend and closed-won jobs."""

    currency: str = Field(default="USD", min_length=3, max_length=3)
    rows: list[SourceROIRow] = Field(default_factory=list)
    winner: LeadSourceWinnerSummary = Field(default_factory=LeadSourceWinnerSummary)
    total_spend: float = Field(default=0.0, ge=0.0)
    total_closed_won_jobs: int = Field(default=0, ge=0)
    total_closed_won_revenue: float = Field(default=0.0, ge=0.0)
    source_types_ranked: list[LeadSourceType] = Field(
        default_factory=lambda: [
            LeadSourceType.FACEBOOK_ADS,
            LeadSourceType.GOOGLE_ADS,
            LeadSourceType.ORGANIC,
            LeadSourceType.PHONE_RADIO,
        ]
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Return dashboard currency codes in uppercase."""
        return v.upper()


class LeadSourceCreate(BaseModel):
    """Schema for creating a lead source."""

    name: str = Field(..., min_length=1, max_length=200)
    allowed_domains: list[str] = Field(default_factory=list)
    source_type: LeadSourceType = LeadSourceType.OTHER
    action: LeadSourceAction = "collect"
    action_config: dict[str, Any] = Field(default_factory=dict)


class LeadSourceUpdate(BaseModel):
    """Schema for updating a lead source."""

    name: str | None = Field(None, min_length=1, max_length=200)
    allowed_domains: list[str] | None = None
    enabled: bool | None = None
    source_type: LeadSourceType | None = None
    action: LeadSourceAction | None = None
    action_config: dict[str, Any] | None = None


class LeadSourceResponse(BaseModel):
    """Schema for lead source response."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    public_key: str
    allowed_domains: list[str]
    enabled: bool
    source_type: LeadSourceType = LeadSourceType.OTHER
    action: str
    action_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    endpoint_url: str = ""

    model_config = {"from_attributes": True}


class LeadSubmitRequest(BaseModel):
    """Public-facing lead submission request."""

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    email: EmailStr | None = None
    phone_number: str = Field(..., min_length=10, max_length=20)
    company_name: str | None = Field(None, max_length=255)
    # Free-form property/mailing address as typed on the customer's website
    # ("14040 Pernell Dr, Sterling Heights, MI 48313"). Parsed server-side
    # into the contact's structured address columns; never dropped.
    address: str | None = Field(None, max_length=500)
    notes: str | None = None
    source_detail: str | None = Field(None, max_length=200)
    lead_source_campaign_id: uuid.UUID | None = None
    attribution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    utm_source: str | None = Field(default=None, max_length=255)
    utm_medium: str | None = Field(default=None, max_length=255)
    utm_campaign: str | None = Field(default=None, max_length=255)
    utm_content: str | None = Field(default=None, max_length=255)
    utm_term: str | None = Field(default=None, max_length=255)
    gclid: str | None = Field(default=None, max_length=255)
    fbclid: str | None = Field(default=None, max_length=255)
    landing_page: str | None = Field(default=None, max_length=2048)
    referrer: str | None = Field(default=None, max_length=2048)

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Validate and normalize phone number to E.164 format."""
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        msg = "Phone number must be a valid US number (10 digits)"
        raise ValueError(msg)

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, v: str) -> str:
        """Validate first name is not empty."""
        if not v or not v.strip():
            msg = "First name is required"
            raise ValueError(msg)
        return v.strip()


class LeadSubmitResponse(BaseModel):
    """Response from public lead submission."""

    success: bool
    message: str
