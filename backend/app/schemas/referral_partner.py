"""Referral partner schemas: CRUD payloads and the partner scoreboard."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.referral_partner import ReferralPartnerType

# Default "gone quiet" window. A partner who normally sends work monthly and has
# been silent for 60 days is the call worth making today; tighter windows flag
# seasonal partners who were never going to refer in February.
DEFAULT_QUIET_AFTER_DAYS = 60


class ReferralPartnerBase(BaseModel):
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
    """A referral partner record."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReferralPartnerListResponse(BaseModel):
    """List of referral partners."""

    items: list[ReferralPartnerResponse]
    total: int


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
