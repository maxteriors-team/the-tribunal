"""Field-service models: service locations, crews, and technicians.

These are the operational backbone for ServiceTitan/Jobber-style dispatch in a
home-service workspace:

- :class:`ServiceLocation` — a physical job site belonging to a customer
  (``contact``). One customer may have many locations (primary residence, a
  rental, a commercial unit). Postal address fields are customer PII and are
  Fernet-encrypted at rest via :class:`app.core.encryption.EncryptedString`,
  matching the posture of :class:`app.models.contact.Contact`. Latitude and
  longitude are stored as plain floats because the dispatch map must render pins
  and run geo queries, which encrypted columns cannot support.
- :class:`Crew` — a named field team (a dispatch lane on the schedule board)
  with a display ``color``. Technicians are assigned to at most one crew.
- :class:`Technician` — a field worker. Optionally linked to a :class:`User`
  login (``user_id``) so a technician can sign in to their own schedule, and
  optionally assigned to a :class:`Crew` (``crew_id``). Technician contact
  details are staff data and are stored in plain text, mirroring
  :class:`app.models.bookable_staff.BookableStaff`.
- :class:`Job` — a unit of field work (a work order) for a customer at a
  service location. Dispatch tags one or more technicians to it (via
  :class:`JobAssignment`) and gives it a time window; each assigned worker then
  sees the job on their calendar. An optional :class:`Crew` lane groups jobs on
  the dispatch board.
- :class:`JobAssignment` — the many-to-many tag between a :class:`Job` and a
  :class:`Technician`. Tagging the same worker twice is a no-op (unique).
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.dialects.postgresql import TEXT as PG_TEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.user import User
    from app.models.workspace import Workspace


class ServiceLocation(Base):
    """A physical job site owned by a customer within a workspace."""

    __tablename__ = "service_locations"
    __table_args__ = (
        Index(
            "ix_service_locations_workspace_contact",
            "workspace_id",
            "contact_id",
        ),
        Index(
            "ix_service_locations_workspace_active",
            "workspace_id",
            "is_active",
        ),
        # One external record (e.g. a Jobber property) maps to at most one
        # service location per workspace, so the one-time import upserts
        # idempotently. Natively created sites leave both columns null.
        Index(
            "uq_service_locations_workspace_external",
            "workspace_id",
            "external_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Human label for the site, e.g. "Main House" or "Rental — 12 Oak St".
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Postal address — customer PII, Fernet-encrypted at rest. Not SQL-queryable;
    # dispatch filtering keys off crew/technician/date rather than address text.
    address_line1: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    city: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    state: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    country: Mapped[str] = mapped_column(
        String(2), nullable=False, default="US", server_default="US"
    )

    # Plain floats so the dispatch map can render pins / run geo queries.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Site access details (gate codes, pets, parking). Sensitive — encrypted.
    access_notes: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)

    # Provenance for sites imported from an external system (e.g. a Jobber
    # property). Together they form the idempotency key for the one-time import
    # (see the partial-unique index in ``__table_args__``).
    external_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
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

    # Relationships. ``workspace`` is bidirectional (workspace-owned entity);
    # ``contact`` is one-directional to avoid widening the encrypted Contact
    # model (cf. Appointment.bookable_staff).
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="service_locations")
    contact: Mapped["Contact"] = relationship("Contact")

    def __repr__(self) -> str:
        return f"<ServiceLocation(id={self.id}, contact_id={self.contact_id}, name={self.name})>"


class Crew(Base):
    """A named field team that appears as a dispatch lane on the schedule."""

    __tablename__ = "crews"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_crews_workspace_name"),
        Index("ix_crews_workspace_active", "workspace_id", "is_active"),
        # One external record (e.g. a Jobber id) maps to at most one crew per
        # workspace, so an idempotent sync can upsert without creating dupes.
        Index(
            "uq_crews_workspace_external",
            "workspace_id",
            "external_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Lane color on the dispatch board (hex, e.g. "#6366f1").
    color: Mapped[str] = mapped_column(
        String(7), nullable=False, default="#6366f1", server_default="#6366f1"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance for records imported from an external system (e.g. Jobber).
    # ``external_source`` names the system ("jobber"); ``external_id`` is that
    # system's stable record id. Both null for crews created natively in the
    # CRM. Together they form the idempotency key for sync (see unique index).
    external_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
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

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="crews")
    technicians: Mapped[list["Technician"]] = relationship("Technician", back_populates="crew")

    def __repr__(self) -> str:
        return f"<Crew(id={self.id}, name={self.name})>"


class Technician(Base):
    """A field worker, optionally linked to a login and assigned to a crew."""

    __tablename__ = "technicians"
    __table_args__ = (
        Index("ix_technicians_workspace_active", "workspace_id", "is_active"),
        Index("ix_technicians_workspace_crew", "workspace_id", "crew_id"),
        # Idempotency key for sync: one external record maps to one technician
        # per workspace. Partial so natively-created technicians (no external
        # id) are not forced onto a single null row.
        Index(
            "uq_technicians_workspace_external",
            "workspace_id",
            "external_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional link to a login so a technician can sign in to their own
    # schedule. SET NULL keeps the technician record if the user is removed.
    # ``users.id`` is an integer PK (see app.models.user.User).
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # A technician belongs to at most one crew; unassigned when null.
    crew_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Staff identity/contact — plain text, mirroring BookableStaff.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Provenance for technicians imported from an external system (e.g. Jobber
    # ``users``). Null for technicians created natively in the CRM. Together
    # they form the idempotency key for sync (see unique index above).
    external_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Skill tags for skill-based dispatch (case-insensitive matching).
    skills: Mapped[list[str]] = mapped_column(ARRAY(PG_TEXT), default=list, nullable=False)

    # Display color for this technician on the schedule grid.
    color: Mapped[str] = mapped_column(
        String(7), nullable=False, default="#0ea5e9", server_default="#0ea5e9"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
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

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="technicians")
    crew: Mapped["Crew | None"] = relationship("Crew", back_populates="technicians")
    # One-directional: a technician may reference a user login without widening
    # the User model with a reverse collection.
    user: Mapped["User | None"] = relationship("User")
    # Job tags pointing at this technician. CASCADE on the FK removes these rows
    # if the technician is deleted.
    job_assignments: Mapped[list["JobAssignment"]] = relationship(
        "JobAssignment", back_populates="technician"
    )

    def __repr__(self) -> str:
        return f"<Technician(id={self.id}, name={self.name}, crew_id={self.crew_id})>"


class JobStatus(StrEnum):
    """Lifecycle of a field-service job (work order).

    ``unscheduled`` — created but has no time window yet (sits in the queue).
    ``scheduled``   — has a ``scheduled_start``/``scheduled_end`` window.
    ``in_progress`` — a technician is actively working it.
    ``completed``   — work is finished.
    ``cancelled``   — called off; kept for history.
    """

    UNSCHEDULED = "unscheduled"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Backed by the Postgres ``field_service_job_status`` enum created in the jobs
# migration. ``create_type=False`` so SQLAlchemy never tries to CREATE/DROP the
# type — the migration owns its lifecycle (cf. ``failed_job_status``).
_JobStatusType = SAEnum(
    JobStatus,
    name="field_service_job_status",
    create_type=False,
    native_enum=True,
    values_callable=lambda enum: [member.value for member in enum],
    validate_strings=True,
)


class Job(Base):
    """A unit of field work (work order) for a customer, shown on calendars."""

    __tablename__ = "field_service_jobs"
    __table_args__ = (
        Index("ix_field_service_jobs_workspace_status", "workspace_id", "status"),
        Index(
            "ix_field_service_jobs_workspace_scheduled_start",
            "workspace_id",
            "scheduled_start",
        ),
        Index("ix_field_service_jobs_workspace_crew", "workspace_id", "crew_id"),
        # One external record (e.g. a Jobber job) maps to at most one job per
        # workspace, so an idempotent sync can upsert without creating dupes.
        Index(
            "uq_field_service_jobs_workspace_external",
            "workspace_id",
            "external_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The customer this job is for.
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The job site. SET NULL keeps the job if the location is removed.
    service_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Optional dispatch lane/crew. SET NULL keeps the job if the crew is removed.
    crew_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Optional billing link: the invoice this job is billed through. Set when a
    # quote converts into both a job and an invoice, or linked manually. Feeds
    # the job's profitability (revenue side). SET NULL keeps the job if the
    # invoice is removed.
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Provenance: the recurring-job template that materialized this job, if any.
    # Set by the recurring-job worker; also a defensive duplicate guard (one job
    # per template per occurrence start). SET NULL keeps the job if the template
    # is removed.
    recurring_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recurring_job_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[JobStatus] = mapped_column(
        _JobStatusType,
        nullable=False,
        default=JobStatus.UNSCHEDULED,
    )

    # Time window. Nullable: a job is "queued"/unscheduled until it gets one.
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Provenance for jobs imported from an external system (e.g. Jobber). Null
    # for jobs created natively in the CRM. Together they form the idempotency
    # key for sync (see partial-unique index above).
    external_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

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
    contact: Mapped["Contact"] = relationship("Contact")
    service_location: Mapped["ServiceLocation | None"] = relationship("ServiceLocation")
    crew: Mapped["Crew | None"] = relationship("Crew")

    # The tag rows. Deleting a job removes its assignments.
    assignments: Mapped[list["JobAssignment"]] = relationship(
        "JobAssignment",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    # Convenience read-only view of the assigned technicians (writes go through
    # ``assignments`` so the unique tag constraint is enforced in one place).
    technicians: Mapped[list["Technician"]] = relationship(
        "Technician",
        secondary="field_service_job_assignments",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, title={self.title}, status={self.status})>"


class JobAssignment(Base):
    """Many-to-many tag linking a :class:`Job` to an assigned :class:`Technician`."""

    __tablename__ = "field_service_job_assignments"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "technician_id", name="uq_field_service_job_assignments_job_tech"
        ),
        # Hot path: "jobs assigned to this technician" (their calendar).
        Index("ix_field_service_job_assignments_technician", "technician_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_service_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    technician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("technicians.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    job: Mapped["Job"] = relationship("Job", back_populates="assignments")
    technician: Mapped["Technician"] = relationship("Technician", back_populates="job_assignments")

    def __repr__(self) -> str:
        return f"<JobAssignment(job_id={self.job_id}, technician_id={self.technician_id})>"
