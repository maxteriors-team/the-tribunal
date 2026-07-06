"""Offer schemas for API validation."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.schemas.lead_magnet import LeadMagnetResponse


# AI Generation Schemas
class OfferGenerationRequest(BaseModel):
    """Request schema for AI offer generation."""

    business_type: str = Field(..., min_length=2, max_length=200)
    target_audience: str = Field(..., min_length=2, max_length=500)
    main_offer: str = Field(..., min_length=2, max_length=500)
    price_point: float | None = Field(default=None, ge=0)
    desired_outcome: str | None = Field(default=None, max_length=500)
    pain_points: list[str] | None = None
    unique_mechanism: str | None = Field(default=None, max_length=500)


class GeneratedHeadline(BaseModel):
    """Generated headline option."""

    text: str
    style: str | None = None


class GeneratedSubheadline(BaseModel):
    """Generated subheadline option."""

    text: str


class GeneratedValueStackItem(BaseModel):
    """Generated value stack item."""

    name: str
    description: str
    value: float


class GeneratedGuarantee(BaseModel):
    """Generated guarantee option."""

    type: str
    days: int
    text: str


class GeneratedUrgency(BaseModel):
    """Generated urgency option."""

    type: str
    text: str
    count: int | None = None


class GeneratedCTA(BaseModel):
    """Generated CTA option."""

    text: str
    subtext: str | None = None


class GeneratedBonusIdea(BaseModel):
    """Generated bonus idea."""

    name: str
    description: str
    value: float
    suggested_type: str


class GeneratedOfferContent(BaseModel):
    """Response schema for generated offer content."""

    success: bool
    error: str | None = None
    headlines: list[GeneratedHeadline] = []
    subheadlines: list[GeneratedSubheadline] = []
    value_stack_items: list[GeneratedValueStackItem] = []
    guarantees: list[GeneratedGuarantee] = []
    urgency_options: list[GeneratedUrgency] = []
    ctas: list[GeneratedCTA] = []
    bonus_ideas: list[GeneratedBonusIdea] = []


class DiscountType(StrEnum):
    """Discount type options."""

    PERCENTAGE = "percentage"
    FIXED = "fixed"
    FREE_SERVICE = "free_service"


class GuaranteeType(StrEnum):
    """Guarantee type options."""

    MONEY_BACK = "money_back"
    SATISFACTION = "satisfaction"
    RESULTS = "results"


class UrgencyType(StrEnum):
    """Urgency type options."""

    LIMITED_TIME = "limited_time"
    LIMITED_QUANTITY = "limited_quantity"
    EXPIRING = "expiring"


class ValueStackItem(BaseModel):
    """Value stack item for Hormozi-style offers."""

    name: str
    description: str | None = None
    value: float = Field(ge=0)
    included: bool = True


class OfferBase(BaseModel):
    """Base offer schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    discount_type: DiscountType = DiscountType.PERCENTAGE
    discount_value: float = Field(default=0, ge=0)
    terms: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool = True

    # Hormozi-style fields
    headline: str | None = Field(default=None, max_length=500)
    subheadline: str | None = None
    regular_price: float | None = Field(default=None, ge=0)
    offer_price: float | None = Field(default=None, ge=0)
    savings_amount: float | None = Field(default=None, ge=0)
    guarantee_type: GuaranteeType | None = None
    guarantee_days: int | None = Field(default=None, ge=0)
    guarantee_text: str | None = None
    urgency_type: UrgencyType | None = None
    urgency_text: str | None = Field(default=None, max_length=255)
    scarcity_count: int | None = Field(default=None, ge=0)
    value_stack_items: list[ValueStackItem] | None = None
    cta_text: str | None = Field(default=None, max_length=100)
    cta_subtext: str | None = Field(default=None, max_length=255)


class OfferCreate(OfferBase):
    """Schema for creating an offer."""

    pass


class OfferUpdate(BaseModel):
    """Schema for updating an offer."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    discount_type: DiscountType | None = None
    discount_value: float | None = Field(default=None, ge=0)
    terms: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool | None = None

    # Hormozi-style fields
    headline: str | None = Field(default=None, max_length=500)
    subheadline: str | None = None
    regular_price: float | None = Field(default=None, ge=0)
    offer_price: float | None = Field(default=None, ge=0)
    savings_amount: float | None = Field(default=None, ge=0)
    guarantee_type: GuaranteeType | None = None
    guarantee_days: int | None = Field(default=None, ge=0)
    guarantee_text: str | None = None
    urgency_type: UrgencyType | None = None
    urgency_text: str | None = Field(default=None, max_length=255)
    scarcity_count: int | None = Field(default=None, ge=0)
    value_stack_items: list[ValueStackItem] | None = None
    cta_text: str | None = Field(default=None, max_length=100)
    cta_subtext: str | None = Field(default=None, max_length=255)
    # Public landing page fields
    is_public: bool | None = None
    public_slug: str | None = Field(default=None, max_length=100)
    require_email: bool | None = None
    require_phone: bool | None = None
    require_name: bool | None = None


class OfferResponse(OfferBase):
    """Schema for offer response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    page_views: int = 0
    opt_ins: int = 0
    created_at: datetime
    updated_at: datetime


class PaginatedOffers(BaseModel):
    """Paginated offers response."""

    items: list[OfferResponse]
    total: int
    page: int
    page_size: int
    pages: int


class OfferCreateWithLeadMagnets(OfferCreate):
    """Schema for creating an offer with lead magnets."""

    lead_magnet_ids: list[uuid.UUID] | None = None


class OfferResponseWithLeadMagnets(OfferResponse):
    """Schema for offer response with attached lead magnets."""

    lead_magnets: list["LeadMagnetResponse"] = []
    total_value: float | None = None  # Computed from value stack + lead magnets


# Import at module level for forward reference resolution
from app.schemas.lead_magnet import LeadMagnetResponse  # noqa: E402, F401

OfferResponseWithLeadMagnets.model_rebuild()


# Public Offer Schemas
class PublicOfferResponse(BaseModel):
    """Public offer response - no sensitive data."""

    model_config = ConfigDict(from_attributes=True)

    # Basic info
    name: str
    headline: str | None = None
    subheadline: str | None = None
    description: str | None = None

    # Pricing
    regular_price: float | None = None
    offer_price: float | None = None
    savings_amount: float | None = None

    # Guarantee
    guarantee_type: str | None = None
    guarantee_days: int | None = None
    guarantee_text: str | None = None

    # Urgency
    urgency_type: str | None = None
    urgency_text: str | None = None
    scarcity_count: int | None = None

    # Value stack
    value_stack_items: list[ValueStackItem] | None = None

    # CTA
    cta_text: str | None = None
    cta_subtext: str | None = None

    # Lead magnet bonuses
    lead_magnets: list[LeadMagnetResponse] = []
    total_value: float | None = None

    # Required fields
    require_email: bool = True
    require_phone: bool = False
    require_name: bool = False

    # Shown in the SMS-consent disclosure (TCR requires the brand name in the CTA)
    business_name: str | None = None


class OptInRequest(BaseModel):
    """Request schema for opt-in submission.

    ``sms_consent`` mirrors the form's optional, unchecked-by-default checkbox
    (TCR/10DLC requirement — error 803 is issued when consent is bundled into
    form submission). Submitting without it must always succeed; it only
    controls whether the contact is recorded as SMS-opted-in.
    """

    email: str | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=255)
    sms_consent: bool = False


class OptInResponse(BaseModel):
    """Response schema for successful opt-in."""

    success: bool
    message: str
    contact_id: int | None = None
    lead_magnet_lead_id: uuid.UUID | None = None
