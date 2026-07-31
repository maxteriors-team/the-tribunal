"""Schemas for pre-booking campaigns: offer terms, audience, reservations.

The offer schema is where the two rules that make pre-booking real are enforced,
before anything reaches the database:

- a **deposit is mandatory and positive** — an offer with no deposit is a
  discount, and a discount holds no slot;
- a **slot cap is mandatory and positive** — an uncapped pre-sell is how a crew
  ends up owing forty driveways in the same week of May.

Everything derived (season dates, lead time, slots remaining, the deposit a
customer would owe) is computed from the shared pure helpers in
:mod:`app.services.prebooking.season` and :mod:`app.services.prebooking.slots`
so the wizard, the API and the charge itself never disagree.
"""

import uuid
from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.models.prebooking import (
    DEFAULT_HOLD_HOURS,
    PreBookingAmountType,
    PreBookingReservationStatus,
)
from app.services.prebooking.season import (
    LeadTimeStatus,
    assess_lead_time,
    describe_season,
    lead_time_days,
    resolve_season_window,
)
from app.services.prebooking.slots import assemble_slot_usage

# A crew that can genuinely deliver more than this in one season is not running
# one calendar, and the cap stops being the safety rail it exists to be.
MAX_SLOT_CAP = 1000

# An unpaid hold longer than a month is indistinguishable from a lost slot.
MAX_HOLD_HOURS = 720


# --------------------------------------------------------------------------- #
# Offer terms
# --------------------------------------------------------------------------- #
class PreBookingConfigBase(BaseModel):
    """Operator-settable pre-booking offer terms."""

    model_config = ConfigDict(extra="forbid")

    service_season_start_month: int = Field(ge=1, le=12)
    service_season_end_month: int = Field(ge=1, le=12)
    # The calendar year the season *starts* in. A season that wraps (Nov -> Feb)
    # derives its end year, so there is only ever one year to get wrong.
    service_season_year: int = Field(ge=2000, le=2100)
    service_description: str = Field(min_length=1, max_length=200)

    incentive_type: PreBookingAmountType = PreBookingAmountType.PERCENTAGE
    incentive_value: float = Field(gt=0)

    deposit_type: PreBookingAmountType = PreBookingAmountType.PERCENTAGE
    # Required and positive on purpose — see the module docstring.
    deposit_value: float = Field(gt=0)

    slot_cap: int = Field(gt=0, le=MAX_SLOT_CAP)
    hold_hours: int = Field(default=DEFAULT_HOLD_HOURS, gt=0, le=MAX_HOLD_HOURS)

    @model_validator(mode="after")
    def _percentages_stay_percentages(self) -> "PreBookingConfigBase":
        """Reject percentages above 100 for either money field.

        A 120% deposit or a 150% discount is always a typo, and both are the kind
        that reaches a customer's phone before anyone notices.
        """
        if self.incentive_type is PreBookingAmountType.PERCENTAGE and self.incentive_value > 100:
            raise ValueError("A percentage incentive cannot exceed 100%")
        if self.deposit_type is PreBookingAmountType.PERCENTAGE and self.deposit_value > 100:
            raise ValueError("A percentage deposit cannot exceed 100%")
        return self


class PreBookingConfigCreate(PreBookingConfigBase):
    """Payload for attaching a pre-booking offer to a campaign."""


class PreBookingConfigUpdate(BaseModel):
    """Partial update of an existing pre-booking offer."""

    model_config = ConfigDict(extra="forbid")

    service_season_start_month: int | None = Field(default=None, ge=1, le=12)
    service_season_end_month: int | None = Field(default=None, ge=1, le=12)
    service_season_year: int | None = Field(default=None, ge=2000, le=2100)
    service_description: str | None = Field(default=None, min_length=1, max_length=200)
    incentive_type: PreBookingAmountType | None = None
    incentive_value: float | None = Field(default=None, gt=0)
    deposit_type: PreBookingAmountType | None = None
    deposit_value: float | None = Field(default=None, gt=0)
    slot_cap: int | None = Field(default=None, gt=0, le=MAX_SLOT_CAP)
    hold_hours: int | None = Field(default=None, gt=0, le=MAX_HOLD_HOURS)


class PreBookingConfigResponse(BaseModel):
    """A campaign's pre-booking offer plus its live slot and lead-time state."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    campaign_id: uuid.UUID

    service_season_start_month: int
    service_season_end_month: int
    service_season_year: int
    service_description: str

    incentive_type: PreBookingAmountType
    incentive_value: float
    deposit_type: PreBookingAmountType
    deposit_value: float

    slot_cap: int
    hold_hours: int

    # Populated by the service from live reservation counts; defaulted so the row
    # can also be validated straight off the ORM object in write paths.
    slots_held: int = 0
    slots_confirmed: int = 0
    # ``scheduled_start`` of the owning campaign, mirrored here so the UI can put
    # the launch date and the season it feeds on the same card. ``None`` until
    # the operator schedules the launch.
    scheduled_start: datetime | None = None

    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def season_start_date(self) -> date:
        """First day the work could be performed."""
        return resolve_season_window(
            start_month=self.service_season_start_month,
            end_month=self.service_season_end_month,
            year=self.service_season_year,
        ).start

    @computed_field  # type: ignore[prop-decorator]
    @property
    def season_end_date(self) -> date:
        """Last day the work could be performed."""
        return resolve_season_window(
            start_month=self.service_season_start_month,
            end_month=self.service_season_end_month,
            year=self.service_season_year,
        ).end

    @computed_field  # type: ignore[prop-decorator]
    @property
    def season_label(self) -> str:
        """Operator-facing season name, e.g. ``"March–May 2027"``."""
        return describe_season(
            start_month=self.service_season_start_month,
            end_month=self.service_season_end_month,
            year=self.service_season_year,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def slots_remaining(self) -> int:
        """Slots still sellable right now."""
        return assemble_slot_usage(
            cap=self.slot_cap, held=self.slots_held, confirmed=self.slots_confirmed
        ).remaining

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_full(self) -> bool:
        """True when no further slot may be held."""
        return assemble_slot_usage(
            cap=self.slot_cap, held=self.slots_held, confirmed=self.slots_confirmed
        ).is_full

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lead_time_days(self) -> int:
        """Days between the scheduled launch (or today) and the season opening."""
        launch = self.scheduled_start.date() if self.scheduled_start else datetime.now(UTC).date()
        return lead_time_days(launch_on=launch, season_start=self.season_start_date)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lead_time_status(self) -> LeadTimeStatus:
        """``ample`` / ``tight`` / ``late`` grading of the runway."""
        return assess_lead_time(self.lead_time_days).status

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lead_time_message(self) -> str:
        """One-line operator guidance about the runway."""
        return assess_lead_time(self.lead_time_days).message


class PreBookingLaunchRequest(BaseModel):
    """Schedule a pre-booking campaign to launch on a future date."""

    model_config = ConfigDict(extra="forbid")

    scheduled_start: datetime


# --------------------------------------------------------------------------- #
# Audience
# --------------------------------------------------------------------------- #
class PreBookingAudienceRequest(BaseModel):
    """Which slice of the warm database to target."""

    model_config = ConfigDict(extra="forbid")

    include_past_customers: bool = True
    include_unsold_quotes: bool = True
    # Last season's holiday-lighting customers. Off by default because it is a
    # far narrower slice than the other two; a renewal push turns those off and
    # this on. ``seasons_back=1`` is strictly last season, ``None`` every season
    # on record.
    include_prior_season_christmas: bool = False
    seasons_back: int | None = Field(default=None, gt=0, le=10)
    # Optional extra narrowing, in the same JSON rule shape a saved
    # :class:`app.models.segment.Segment` uses, resolved by the shared contact
    # filter engine rather than a second query language.
    segment_id: uuid.UUID | None = None
    limit: int | None = Field(default=None, gt=0, le=5000)


class PreBookingAudiencePreview(BaseModel):
    """Counts behind a pre-booking audience, before anyone is enrolled."""

    total: int
    past_customers: int
    unsold_quotes: int
    # Counted whether or not the slice is selected, so an operator sees how many
    # homes were lit last season before deciding to aim at them.
    prior_season_christmas: int = 0
    # Warm contacts held back because they told us to stop. Surfaced rather than
    # silently dropped: "why is my list smaller than my database" has exactly one
    # honest answer.
    excluded_opted_out: int
    excluded_already_enrolled: int


class PreBookingAudienceEnrollResponse(BaseModel):
    """Result of enrolling the warm audience into the campaign."""

    enrolled: int
    skipped_already_enrolled: int
    excluded_opted_out: int
    total_contacts: int


# --------------------------------------------------------------------------- #
# Reservations
# --------------------------------------------------------------------------- #
class PreBookingReserveRequest(BaseModel):
    """Accept the pre-booking offer for one contact."""

    model_config = ConfigDict(extra="forbid")

    contact_id: int
    # Re-price last year's unsold quote at the pre-booking discount. Its line
    # items are copied so the customer sees the job they already recognise.
    source_quote_id: uuid.UUID | None = None
    # Used when there is no source quote: the pre-discount price of the work.
    base_amount: float | None = Field(default=None, gt=0)
    service_location_id: uuid.UUID | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _needs_a_price(self) -> "PreBookingReserveRequest":
        if self.source_quote_id is None and self.base_amount is None:
            raise ValueError("Provide either source_quote_id or base_amount")
        return self


class PreBookingReservationResponse(BaseModel):
    """One contact's claim on a season slot."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    campaign_id: uuid.UUID
    config_id: uuid.UUID
    contact_id: int
    quote_id: uuid.UUID | None
    job_id: uuid.UUID | None
    status: PreBookingReservationStatus
    target_start_date: date
    target_end_date: date
    quoted_total: float | None
    incentive_amount: float | None
    deposit_amount: float | None
    held_at: datetime
    hold_expires_at: datetime
    confirmed_at: datetime | None
    released_at: datetime | None
    release_reason: str | None
    created_at: datetime


class PreBookingReserveResponse(BaseModel):
    """A held slot plus the link the customer pays their deposit through."""

    reservation: PreBookingReservationResponse
    quote_id: uuid.UUID
    quote_number: str
    deposit_amount: float
    # The existing public client-proposal page. Paying its deposit is what
    # confirms the reservation — there is no second payment path.
    proposal_url: str
    slots_remaining: int
