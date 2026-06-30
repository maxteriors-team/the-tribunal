"""Recurring job templates (maintenance contracts).

A :class:`RecurringJobTemplate` describes a job that should repeat on a schedule
— the classic "quarterly HVAC service" or "weekly lawn care" maintenance
contract. A background worker (:mod:`app.workers.recurring_job_worker`)
materializes the next concrete :class:`app.models.field_service.Job` from each
active template as its due date approaches, copying the template's customer,
site, crew, default technicians, and title/description onto the generated job.

The template carries its own cursor (``next_run_at``) which the worker advances
by ``interval`` × ``frequency`` after each materialization, so generation is
idempotent per period: a job is created for a given occurrence exactly once.
Generated jobs link back via ``Job.recurring_template_id`` for provenance and as
a defensive duplicate guard.

Frequency is stored as a short ``String`` (not a Postgres enum) so the schedule
vocabulary can grow without a type migration — the allowed values are enforced by
:class:`RecurrenceFrequency` at the schema/service boundary, mirroring the
enum-free posture of the job-costing models.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.field_service import Crew, ServiceLocation
    from app.models.user import User
    from app.models.workspace import Workspace


class RecurrenceFrequency(StrEnum):
    """How often a recurring job repeats.

    ``interval`` multiplies these (e.g. ``frequency=weekly, interval=2`` is every
    two weeks; ``biweekly`` is provided as a convenience alias for that common
    case).
    """

    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class RecurringJobTemplate(Base):
    """A maintenance-contract template that materializes jobs on a schedule."""

    __tablename__ = "recurring_job_templates"
    __table_args__ = (
        Index(
            "ix_recurring_job_templates_workspace_active",
            "workspace_id",
            "is_active",
        ),
        # Hot path for the worker: active templates whose next occurrence is due.
        Index(
            "ix_recurring_job_templates_due",
            "is_active",
            "next_run_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The customer this contract serves.
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The job site. SET NULL keeps the template if the location is removed.
    service_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Default dispatch lane/crew for generated jobs.
    crew_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Copied onto each generated job.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Schedule. ``frequency`` is validated against RecurrenceFrequency at the
    # schema boundary; ``interval`` repeats every N periods (>= 1).
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # Length of each generated job's time window, in minutes.
    duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )
    # Materialize the job this many days before its scheduled start, so dispatch
    # and the customer see it on the board ahead of time.
    generate_days_ahead: Mapped[int] = mapped_column(
        Integer, nullable=False, default=14, server_default="14"
    )

    # Default technicians tagged onto each generated job. Stored inline (not a
    # join table) because it is a small ordered preference list, not a queried
    # relationship; the worker validates each id still exists before assigning.
    default_technician_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )

    # Cursor for the next occurrence to generate. The worker advances this by
    # interval × frequency after each materialization.
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # When a job was last materialized from this template (null until the first).
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
    contact: Mapped["Contact"] = relationship("Contact")
    service_location: Mapped["ServiceLocation | None"] = relationship("ServiceLocation")
    crew: Mapped["Crew | None"] = relationship("Crew")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self) -> str:
        return (
            f"<RecurringJobTemplate(id={self.id}, title={self.title}, "
            f"frequency={self.frequency}, next_run_at={self.next_run_at})>"
        )
