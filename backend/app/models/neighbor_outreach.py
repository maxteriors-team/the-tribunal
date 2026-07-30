"""Neighbor outreach: the persisted "work the street" list for a finished job.

When a crew finishes a job, the houses that watched them work are the warmest
cold audience in home services — this is the mechanism that makes a wrapped truck
and a yard sign compound instead of just generating impressions. Finding those
houses is :mod:`app.services.field_service.jobsite_radius`; *remembering* them is
this module.

- :class:`NeighborOutreachBatch` — one batch per completed :class:`Job` (unique on
  ``job_id``). Regenerating tops the same batch up rather than creating a second
  one, which is what makes "the same neighbour is never worked twice for the same
  job" a database guarantee instead of a convention. It snapshots the origin
  coordinates and radius so the list stays explainable after the site or the
  workspace's radius setting changes.
- :class:`NeighborOutreachEntry` — one neighbouring :class:`ServiceLocation` in a
  batch, with the operator's per-entry status (``pending`` → ``contacted`` /
  ``skipped`` / ``converted``). Unique on ``(batch_id, service_location_id)``.

**Channel is print-first by design.** ``channel`` defaults to
:attr:`NeighborOutreachChannel.PRINT` (door hanger / direct mail / canvass). SMS
and email are only ever assigned to an entry whose location maps to a known
:class:`~app.models.contact.Contact` that has SMS consent and is not on the
workspace's opt-out list — cold-messaging strangers harvested from a radius is a
TCPA problem, not a growth channel. ``messaging_blocked_reason`` persists *why* an
entry stayed print-only so the decision is auditable after the fact.

No address is copied onto an entry. A site's postal fields are
:class:`app.core.encryption.EncryptedString` on
:class:`~app.models.field_service.ServiceLocation`, and duplicating customer PII
into a second table to save a join is how encryption posture rots. The export
reads through the ``service_location`` relationship instead.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.field_service import Job, ServiceLocation
    from app.models.workspace import Workspace


class NeighborOutreachStatus(StrEnum):
    """Where one neighbour stands in the outreach for a given job.

    ``pending``   — generated, not yet worked.
    ``contacted`` — a door hanger was hung / a mailer went out / a message sent.
    ``skipped``   — deliberately passed over (vacant, hostile, already a customer).
    ``converted`` — turned into a lead or a booked job.

    Persisted as ``VARCHAR(50)`` (``native_enum=False``, ``create_constraint=False``),
    not a Postgres ``ENUM``, so a future status needs no ``ALTER TYPE`` migration —
    the same treatment as :class:`app.models.referral_partner.ReferralPartnerType`.
    Keep values under 50 chars.
    """

    PENDING = "pending"
    CONTACTED = "contacted"
    SKIPPED = "skipped"
    CONVERTED = "converted"


class NeighborOutreachChannel(StrEnum):
    """How this neighbour is to be reached.

    ``print`` is the default and the only channel available for a location with no
    consented contact behind it: a door hanger or a mailer needs no prior
    relationship. ``sms``/``email`` are assigned only after the compliance gate in
    :mod:`app.services.field_service.neighbor_outreach` clears the location's
    contact. Same ``VARCHAR(50)`` treatment as :class:`NeighborOutreachStatus`.
    """

    PRINT = "print"
    SMS = "sms"
    EMAIL = "email"


_STATUS_TYPE = SAEnum(
    NeighborOutreachStatus,
    native_enum=False,
    create_constraint=False,
    length=50,
    values_callable=lambda enum: [member.value for member in enum],
)

_CHANNEL_TYPE = SAEnum(
    NeighborOutreachChannel,
    native_enum=False,
    create_constraint=False,
    length=50,
    values_callable=lambda enum: [member.value for member in enum],
)


class NeighborOutreachBatch(Base):
    """The neighbour list generated for one job, at one radius, at one moment."""

    __tablename__ = "neighbor_outreach_batches"
    __table_args__ = (
        # One batch per job. This is the idempotency guard that makes a repeated
        # "generate" (an operator clicking twice, or the completion hook racing a
        # manual run) top up an existing batch instead of duplicating the street.
        UniqueConstraint("job_id", name="uq_neighbor_outreach_batches_job"),
        Index("ix_neighbor_outreach_batches_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The completed job this street was worked off. CASCADE: deleting the job
    # deletes the list it produced, which has no meaning without it.
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_service_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The job's own site — the centre of the circle. SET NULL keeps the batch if
    # the site is later removed; the snapshot coordinates below keep it usable.
    origin_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Snapshot of the search so the list stays explainable: coordinates because
    # the site may be re-geocoded, radius because the workspace setting may change.
    origin_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    origin_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_meters: Mapped[int] = mapped_column(Integer, nullable=False)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
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

    # One-directional to ``Workspace``/``Job``/``ServiceLocation``: this is a
    # leaf-ish record and widening those models with reverse collections buys
    # nothing (cf. ``ServiceLocation.contact``).
    workspace: Mapped["Workspace"] = relationship("Workspace")
    job: Mapped["Job"] = relationship("Job")
    origin_location: Mapped["ServiceLocation | None"] = relationship("ServiceLocation")
    entries: Mapped[list["NeighborOutreachEntry"]] = relationship(
        "NeighborOutreachEntry",
        back_populates="batch",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<NeighborOutreachBatch(id={self.id}, job_id={self.job_id}, "
            f"radius_meters={self.radius_meters})>"
        )


class NeighborOutreachEntry(Base):
    """One neighbouring site inside a batch, with its worked/skipped status."""

    __tablename__ = "neighbor_outreach_entries"
    __table_args__ = (
        # The core promise: one row per neighbour per job, so a regenerate or a
        # concurrent generate can never queue the same house twice for the same
        # job (and can never reset a status an operator already set).
        UniqueConstraint(
            "batch_id",
            "service_location_id",
            name="uq_neighbor_outreach_entries_batch_location",
        ),
        Index("ix_neighbor_outreach_entries_workspace_status", "workspace_id", "status"),
        Index("ix_neighbor_outreach_entries_batch_distance", "batch_id", "distance_meters"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Denormalized tenant column so every read is scoped through
    # :mod:`app.db.scope` without a join back to the batch.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("neighbor_outreach_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The neighbouring job site. CASCADE: an entry is meaningless without it.
    service_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The customer behind the site, when there is one. Nullable so an address-only
    # canvass row stays representable; a null here is what forces ``print``.
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Straight-line metres from the job site. Sortable, and the number an operator
    # uses to decide how far to walk.
    distance_meters: Mapped[float] = mapped_column(Float, nullable=False)

    status: Mapped[NeighborOutreachStatus] = mapped_column(
        _STATUS_TYPE,
        nullable=False,
        default=NeighborOutreachStatus.PENDING,
        server_default=NeighborOutreachStatus.PENDING.value,
    )
    channel: Mapped[NeighborOutreachChannel] = mapped_column(
        _CHANNEL_TYPE,
        nullable=False,
        default=NeighborOutreachChannel.PRINT,
        server_default=NeighborOutreachChannel.PRINT.value,
    )

    # Why this entry is print-only ("no_contact", "missing_sms_consent",
    # "global_opt_out", "no_phone_number", ...). Null when messaging is allowed.
    # Persisted so a compliance question months later has an answer.
    messaging_blocked_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Operator notes ("dog, leave at gate", "asked for a quote in spring").
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    batch: Mapped["NeighborOutreachBatch"] = relationship(
        "NeighborOutreachBatch", back_populates="entries"
    )
    service_location: Mapped["ServiceLocation"] = relationship("ServiceLocation")
    contact: Mapped["Contact | None"] = relationship("Contact")

    def __repr__(self) -> str:
        return (
            f"<NeighborOutreachEntry(id={self.id}, batch_id={self.batch_id}, "
            f"status={self.status}, channel={self.channel})>"
        )
