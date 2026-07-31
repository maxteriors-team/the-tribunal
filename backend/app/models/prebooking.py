"""Pre-booking: selling next season's work during this season's dry hole.

A metro-Detroit exteriors business earns May–October and starves December–March.
The CRM already prices seasonal work (:mod:`app.schemas.pricing`) and already
runs SMS/voice/email campaigns, but nothing sold *future-dated* work, which is
the only lever that turns a dry January into a survivable one.

Pre-booking is not a new delivery channel — it is an **offer** bolted onto an
existing :class:`~app.models.campaign.Campaign`:

- :class:`PreBookingCampaignConfig` — the offer terms hung off one campaign
  (which months the work will actually be performed, the discount that buys the
  early commitment, the deposit that makes it real, and the slot cap that stops
  the crew calendar being oversold). A campaign with one of these rows is a
  "pre-booking campaign"; its ``campaign_type`` stays ``sms``/``email`` so every
  existing worker, compliance check and stat counter keeps working untouched.
- :class:`PreBookingReservation` — one contact's claim on one of those slots.
  It holds the slot while the deposit is outstanding and confirms when the money
  lands, linking the :class:`~app.models.quote.Quote` that collected the deposit
  to the provisional :class:`~app.models.field_service.Job` that puts the work
  into backlog.

Why a sidecar table instead of columns on ``campaigns``: the offer is optional
for all but a handful of campaigns, so the alternative is nine nullable columns
that every SMS campaign carries forever. A 1:1 row also lets the cap live on a
single row that can be locked (``FOR UPDATE``) while slots are counted, which is
what makes "never oversell" a real guarantee instead of a race.
"""

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    DATE,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.contact import Contact
    from app.models.field_service import Job
    from app.models.quote import Quote
    from app.models.workspace import Workspace


class PreBookingAmountType(StrEnum):
    """How a money field is read: a percentage of the job, or a flat amount.

    Shared by the booking incentive and the deposit so the two read the same way
    on screen and in the API, and so the deposit maps 1:1 onto the quote's
    existing ``deposit_percentage`` / ``deposit_amount_fixed`` pair.
    """

    PERCENTAGE = "percentage"
    FIXED = "fixed"


class PreBookingReservationStatus(StrEnum):
    """Lifecycle of one contact's claim on a season slot.

    ``held``      — a quote was issued and the deposit is outstanding. Occupies a
                    slot until ``hold_expires_at`` passes.
    ``confirmed`` — the deposit landed. Occupies a slot until the work is done.
    ``released``  — the hold lapsed (or was released) without payment; the slot
                    went back to the pool.
    ``cancelled`` — an operator or customer called the booking off after it was
                    confirmed.
    """

    HELD = "held"
    CONFIRMED = "confirmed"
    RELEASED = "released"
    CANCELLED = "cancelled"


# Statuses that occupy a slot on the crew calendar. ``held`` only counts while
# its hold is still live — expiry is evaluated in the query rather than by a
# sweep, so an abandoned checkout frees its slot the instant it lapses instead of
# whenever a worker next runs. See
# :func:`app.services.prebooking.slots.assemble_slot_usage`.
OCCUPYING_RESERVATION_STATUSES = frozenset(
    {PreBookingReservationStatus.HELD, PreBookingReservationStatus.CONFIRMED}
)

# How long an unpaid hold keeps its slot by default. Long enough for "I'll pay
# tonight when I'm off the roof", short enough that a January campaign is not
# still holding a May slot for someone who never intended to pay.
DEFAULT_HOLD_HOURS = 72


class PreBookingCampaignConfig(Base):
    """Pre-booking offer terms attached to exactly one campaign."""

    __tablename__ = "prebooking_campaign_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # One offer per campaign: the unique constraint is what makes ``pre_booking``
    # a safe ``uselist=False`` relationship rather than a convention.
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # --- The season being sold ------------------------------------------- #
    # Months (1-12) the work will actually be performed, plus the calendar year
    # the window *starts* in. Stored as month numbers rather than two dates
    # because the operator thinks in seasons ("March through May"), and because a
    # season that wraps the new year (Nov -> Feb) then needs no second year
    # column: the end year is derived. See
    # :func:`app.services.prebooking.season.resolve_season_window`.
    service_season_start_month: Mapped[int] = mapped_column(Integer, nullable=False)
    service_season_end_month: Mapped[int] = mapped_column(Integer, nullable=False)
    service_season_year: Mapped[int] = mapped_column(Integer, nullable=False)

    # What the customer is pre-buying, e.g. "Spring house wash + gutter clean".
    # Becomes the quote title and the provisional job's title, so it has to read
    # like something a homeowner recognises months later on a bank statement.
    service_description: Mapped[str] = mapped_column(String(200), nullable=False)

    # --- The trade: discount now for money now --------------------------- #
    incentive_type: Mapped[PreBookingAmountType] = mapped_column(
        SAEnum(
            PreBookingAmountType,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PreBookingAmountType.PERCENTAGE,
    )
    incentive_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    # The deposit that turns a "yeah, maybe in spring" into a booking. Required
    # and positive by schema validation: a pre-booking campaign without a deposit
    # is just a discount, and discounts do not hold slots.
    deposit_type: Mapped[PreBookingAmountType] = mapped_column(
        SAEnum(
            PreBookingAmountType,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PreBookingAmountType.PERCENTAGE,
    )
    deposit_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    # --- The crew calendar guard ----------------------------------------- #
    # How many jobs the crew can actually deliver in this window. Enforced under
    # a row lock on this row, so two customers paying at the same instant cannot
    # both take the last slot.
    slot_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    hold_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_HOLD_HOURS, server_default=str(DEFAULT_HOLD_HOURS)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="pre_booking")
    reservations: Mapped[list["PreBookingReservation"]] = relationship(
        "PreBookingReservation",
        back_populates="config",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<PreBookingCampaignConfig(campaign_id={self.campaign_id}, "
            f"season={self.service_season_start_month}-{self.service_season_end_month} "
            f"{self.service_season_year}, slot_cap={self.slot_cap})>"
        )


class PreBookingReservation(Base):
    """One contact's claim on a season slot, from quote through paid deposit."""

    __tablename__ = "prebooking_reservations"
    __table_args__ = (
        Index("ix_prebooking_reservations_config_status", "config_id", "status"),
        Index("ix_prebooking_reservations_workspace_status", "workspace_id", "status"),
        # A contact may re-book a season they released or cancelled, but may not
        # hold two live claims on the same campaign — otherwise one enthusiastic
        # customer clicking twice eats two slots. Partial so released/cancelled
        # history stays queryable without blocking a genuine second attempt.
        Index(
            "uq_prebooking_reservations_active_contact",
            "campaign_id",
            "contact_id",
            unique=True,
            postgresql_where=text("status IN ('held', 'confirmed')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prebooking_campaign_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized from ``config`` so the "one live claim per campaign" index can
    # be enforced without a join.
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The quote that carries the deposit terms and the public payment link. This
    # is the *only* payment path: the deposit is collected by the existing Stripe
    # checkout on the client proposal page (:mod:`app.services.payments`).
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The provisional work order created once the deposit clears, so pre-sold
    # work shows up in ``backlog_weeks`` instead of being invisible until spring.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_service_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[PreBookingReservationStatus] = mapped_column(
        SAEnum(
            PreBookingReservationStatus,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PreBookingReservationStatus.HELD,
    )

    # The window the work was sold into, snapshotted from the config at hold time
    # so a later edit to the campaign cannot silently move a customer's booking.
    target_start_date: Mapped[date] = mapped_column(DATE, nullable=False)
    target_end_date: Mapped[date] = mapped_column(DATE, nullable=False)

    # Money snapshot (major units), for reporting without re-reading the quote.
    quoted_total: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    incentive_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    deposit_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    held_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    hold_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    config: Mapped["PreBookingCampaignConfig"] = relationship(
        "PreBookingCampaignConfig", back_populates="reservations"
    )
    campaign: Mapped["Campaign"] = relationship("Campaign")
    contact: Mapped["Contact"] = relationship("Contact")
    quote: Mapped["Quote | None"] = relationship("Quote")
    job: Mapped["Job | None"] = relationship("Job")

    def __repr__(self) -> str:
        return (
            f"<PreBookingReservation(id={self.id}, contact_id={self.contact_id}, "
            f"status={self.status})>"
        )
