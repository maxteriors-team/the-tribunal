"""Service plans: the persisted record of what a client signed up for.

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

``plan_type`` is what makes this table a *Service Plan* rather than a bare
schedule: it records which subscription the client bought.
:class:`ServicePlanType.LIGHTING_CARE_PLAN` rows carry the tier the client picked
on their proposal (``care_plan_tier``), and Christmas signups become a **pair**
of :class:`ServicePlanType.CHRISTMAS_LIGHTS` rows (install and takedown) because
those are genuinely different dispatchable jobs — different crew, duration, and
checklist. Both are provisioned from the approved quote (``source_quote_id``) by
:mod:`app.services.recurring_jobs.service_plan_provisioner`, and the partial
unique index on ``(source_quote_id, plan_type, title)`` makes re-approving a
quote a no-op instead of a double signup.

Frequency and plan type are stored as short ``String`` columns (not Postgres
enums) so the schedule/plan vocabulary can grow without a type migration — the
allowed values are enforced by :class:`RecurrenceFrequency` and
:class:`ServicePlanType` at the schema/service boundary, mirroring the enum-free
posture of the job-costing models.
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
    text,
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


class ServicePlanType(StrEnum):
    """Which recurring service a client signed up for.

    ``LIGHTING_CARE_PLAN`` is the landscape-lighting maintenance subscription
    (the tier the client selected lives in ``care_plan_tier``).
    ``CHRISTMAS_LIGHTS`` covers the seasonal holiday signup, which is stored as
    an install plan plus a takedown plan. ``MAINTENANCE`` is the generic
    hand-built contract every pre-existing row backfills to.
    """

    LIGHTING_CARE_PLAN = "lighting_care_plan"
    CHRISTMAS_LIGHTS = "christmas_lights"
    MAINTENANCE = "maintenance"


class RecurringJobTemplate(Base):
    """A service plan: what a client signed up for, and how it materializes."""

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
        # Backs the Service Plans list filtered by plan type.
        Index(
            "ix_recurring_job_templates_workspace_plan_type",
            "workspace_id",
            "plan_type",
        ),
        # Authoritative guard against double-provisioning: approving the same
        # quote twice (operator retry, client double-click on the public page)
        # must not sign the client up twice. ``title`` is part of the key because
        # a Christmas signup provisions an install *and* a takedown plan that
        # share both the quote and the plan type.
        Index(
            "uq_recurring_job_templates_source_quote_plan",
            "source_quote_id",
            "plan_type",
            "title",
            unique=True,
            postgresql_where=text("source_quote_id IS NOT NULL"),
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

    # Which subscription this plan represents. Validated against
    # ``ServicePlanType`` at the schema boundary; rows predating service plans
    # backfill to ``maintenance`` via the server default.
    plan_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ServicePlanType.MAINTENANCE, server_default="maintenance"
    )
    # Care Plan tier the client picked (``ProposalCarePlan.selected``), for
    # ``lighting_care_plan`` plans only.
    care_plan_tier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The approved quote this plan was provisioned from. SET NULL keeps the
    # client's plan alive if the quote is ever deleted.
    source_quote_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Copied onto each generated job.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Schedule. ``frequency`` is validated against RecurrenceFrequency at the
    # schema boundary; ``interval`` repeats every N periods (>= 1).
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
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
            f"plan_type={self.plan_type}, frequency={self.frequency}, "
            f"next_run_at={self.next_run_at})>"
        )
