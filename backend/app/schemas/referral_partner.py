"""Referral partner schemas: CRUD payloads and the partner scoreboard."""

import re
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.models.referral_partner import (
    ReferralPartnerIntakeStatus,
    ReferralPartnerOfferType,
    ReferralPartnerType,
)

# Default "gone quiet" window. A partner who normally sends work monthly and has
# been silent for 60 days is the call worth making today; tighter windows flag
# seasonal partners who were never going to refer in February.
DEFAULT_QUIET_AFTER_DAYS = 60

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PHONE = re.compile(r"^[0-9+() .-]{7,50}(?:\s*(?:x|ext\.?)\s*\d{1,8})?$", re.IGNORECASE)
_HTTP_URL = TypeAdapter(HttpUrl)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if _CONTROL_CHARS.search(cleaned):
        raise ValueError("Text contains unsupported control characters")
    return cleaned


def _clean_website(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    parsed = _HTTP_URL.validate_python(cleaned)
    if parsed.username or parsed.password:
        raise ValueError("Website URL cannot contain credentials")
    return str(parsed)


class ReferralPartnerProfileFields(BaseModel):
    """Public profile and normalized offer fields shared by staff responses."""

    website_url: str | None = Field(default=None, max_length=2048)
    business_description: str | None = Field(default=None, max_length=5000)
    services: str | None = Field(default=None, max_length=5000)
    service_area: str | None = Field(default=None, max_length=500)
    offer_headline: str | None = Field(default=None, max_length=200)
    offer_description: str | None = Field(default=None, max_length=3000)
    offer_type: ReferralPartnerOfferType = ReferralPartnerOfferType.NONE
    offer_value: Decimal | None = Field(default=None, ge=0, le=999_999_999.99)
    offer_terms: str | None = Field(default=None, max_length=3000)

    @field_validator("website_url", mode="before")
    @classmethod
    def validate_website(cls, value: str | None) -> str | None:
        return _clean_website(value)

    @field_validator(
        "business_description",
        "services",
        "service_area",
        "offer_headline",
        "offer_description",
        "offer_terms",
        mode="before",
    )
    @classmethod
    def clean_profile_text(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @model_validator(mode="after")
    def validate_offer(self) -> "ReferralPartnerProfileFields":
        valued_types = {
            ReferralPartnerOfferType.FIXED_DOLLAR_CREDIT,
            ReferralPartnerOfferType.PERCENTAGE_DISCOUNT,
        }
        if self.offer_type in valued_types and self.offer_value is None:
            raise ValueError("This offer type requires a value")
        if self.offer_type not in valued_types and self.offer_value is not None:
            raise ValueError("This offer type does not accept a value")
        if (
            self.offer_type == ReferralPartnerOfferType.PERCENTAGE_DISCOUNT
            and self.offer_value is not None
            and self.offer_value > 100
        ):
            raise ValueError("Percentage offer value cannot exceed 100")
        return self


class ReferralPartnerBase(ReferralPartnerProfileFields):
    """Shared referral-partner fields."""

    name: str = Field(..., min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    partner_type: ReferralPartnerType = ReferralPartnerType.OTHER
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=5000)
    contact_id: int | None = Field(
        default=None, description="Existing CRM contact this partner already is, if any"
    )
    is_active: bool = True

    @field_validator("name", "company", "phone", "notes", mode="before")
    @classmethod
    def clean_partner_text(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is not None and not _PHONE.fullmatch(value):
            raise ValueError("Enter a valid phone number")
        return value


class ReferralPartnerCreate(ReferralPartnerBase):
    """Create a referral partner."""


class ReferralPartnerUpdate(BaseModel):
    """Partial update for a referral partner."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    partner_type: ReferralPartnerType | None = None
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=5000)
    contact_id: int | None = None
    is_active: bool | None = None


class ReferralPartnerResponse(ReferralPartnerBase):
    """A referral partner record, including its submitted public profile."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    intake_status: ReferralPartnerIntakeStatus = ReferralPartnerIntakeStatus.NOT_REQUESTED
    intake_link_created_at: datetime | None = None
    intake_submitted_at: datetime | None = None
    intake_revoked_at: datetime | None = None
    has_logo: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReferralPartnerListResponse(BaseModel):
    """List of referral partners."""

    items: list[ReferralPartnerResponse]
    total: int


class ReferralPartnerIntakeLinkResponse(BaseModel):
    """An authenticated user's copyable public intake capability."""

    intake_url: str
    created_at: datetime
    expires_at: datetime
    status: ReferralPartnerIntakeStatus


class PublicReferralPartnerIntake(BaseModel):
    """Safe editable prefill only; never exposes tenant, CRM, or internal fields."""

    name: str
    company: str | None
    partner_type: ReferralPartnerType
    email: EmailStr | None
    phone: str | None
    website_url: str | None
    business_description: str | None
    services: str | None
    service_area: str | None
    offer_headline: str | None
    offer_description: str | None
    offer_type: ReferralPartnerOfferType
    offer_value: Decimal | None
    offer_terms: str | None
    intake_status: ReferralPartnerIntakeStatus
    intake_submitted_at: datetime | None
    has_logo: bool = False


class PublicReferralPartnerIntakeSubmit(ReferralPartnerProfileFields):
    """Required profile fields; internal CRM classification is deliberately excluded."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=50)
    website_url: str = Field(min_length=1, max_length=2048)
    business_description: str = Field(min_length=1, max_length=5000)
    services: str = Field(min_length=1, max_length=5000)
    service_area: str = Field(min_length=1, max_length=500)
    offer_headline: str = Field(min_length=1, max_length=200)
    offer_description: str = Field(min_length=1, max_length=3000)
    offer_type: ReferralPartnerOfferType
    offer_terms: str = Field(min_length=1, max_length=3000)

    @field_validator("name", "company", "phone", mode="before")
    @classmethod
    def clean_contact_text(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("phone")
    @classmethod
    def validate_public_phone(cls, value: str) -> str:
        if not _PHONE.fullmatch(value):
            raise ValueError("Enter a valid phone number")
        return value


class ReferralPartnerLogoResponse(BaseModel):
    """Logo metadata only; bytes are served from a dedicated endpoint."""

    model_config = ConfigDict(from_attributes=True)

    content_type: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime


class ReferralPartnerScoreboardRow(BaseModel):
    """One partner's production, as the owner would read it off a whiteboard.

    ``close_rate`` is the share of *referred leads* that produced at least one
    booked job, so it is bounded at 1.0 even when a single referred customer buys
    twice. ``jobs_closed`` and ``total_revenue`` count every canonical booking,
    which is why ``average_job_value`` divides by ``jobs_closed`` rather than by
    the referral count. Both rates are ``None`` — not ``0.0`` — when their
    denominator is zero, so "no data yet" never renders as a 0% failure.
    """

    partner_id: uuid.UUID
    name: str
    company: str | None = None
    partner_type: ReferralPartnerType
    is_active: bool = True
    referrals_sent: int = Field(default=0, ge=0)
    jobs_closed: int = Field(default=0, ge=0)
    close_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    total_revenue: float = Field(default=0.0, ge=0.0)
    average_job_value: float | None = Field(default=None, ge=0.0)
    last_referral_at: datetime | None = None
    days_since_last_referral: int | None = Field(default=None, ge=0)
    # True when the partner has referred before but not inside the quiet window.
    # This is the call list.
    is_gone_quiet: bool = False


class ReferralPartnerScoreboardResponse(BaseModel):
    """Partner scoreboard, ranked by canonical booked revenue descending."""

    items: list[ReferralPartnerScoreboardRow]
    total: int
    # Echoed back so the UI can label the column ("quiet 60+ days") using the
    # window the server actually applied rather than its own assumption.
    quiet_after_days: int = Field(default=DEFAULT_QUIET_AFTER_DAYS, ge=1)
    gone_quiet_only: bool = False
    currency: str = Field(default="USD", min_length=3, max_length=3)
    total_referrals_sent: int = Field(default=0, ge=0)
    total_jobs_closed: int = Field(default=0, ge=0)
    total_revenue: float = Field(default=0.0, ge=0.0)
