"""Field-execution models: job time entries and expenses.

These hang off :class:`app.models.field_service.Job` and power basic job
profitability (revenue from the linked invoice minus labor and expenses):

- :class:`TimeEntry` — a span of work a technician logged against a job, either
  via clock-in/clock-out (``ended_at`` null while the clock is running) or a
  manual start/end. An hourly ``rate`` (major units) lets the costing service
  turn tracked time into a labor cost; it defaults to 0 so time can be tracked
  without a rate.
- :class:`JobExpense` — a single cost incurred on a job (materials, fuel, a
  subcontractor), in major units.

Money is stored via ``Numeric`` to match :mod:`app.models.invoice`.
"""

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DATE,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.field_service import Job, Technician
    from app.models.user import User
    from app.models.workspace import Workspace


class TimeEntry(Base, WorkspaceScoped):
    """A span of work logged by a technician against a job."""

    __tablename__ = "job_time_entries"
    __table_args__ = (
        Index("ix_job_time_entries_workspace_job", "workspace_id", "job_id"),
        # Hot path for the "am I clocked in?" check and timer lookup.
        Index("ix_job_time_entries_job_open", "job_id", "ended_at"),
        Index(
            "uq_job_time_entries_open_creator",
            "workspace_id",
            "job_id",
            "created_by_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL AND created_by_id IS NOT NULL"),
        ),
        CheckConstraint(
            "stop_reason IS NULL OR "
            "(ended_at IS NOT NULL AND stop_reason IN ('paused', 'ended', 'manual'))",
            name="stop_reason",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_service_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Who logged the time. SET NULL keeps the entry if the technician is removed.
    technician_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("technicians.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Null while the clock is running; set when paused, ended, or entered manually.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Null for active and legacy entries. New completed entries record why they stopped.
    stop_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Hourly cost rate (major units). Labor cost = hours * rate.
    rate: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    job: Mapped["Job"] = relationship("Job")
    technician: Mapped["Technician | None"] = relationship("Technician")
    workspace: Mapped["Workspace"] = relationship("Workspace")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self) -> str:
        return (
            f"<TimeEntry(id={self.id}, job_id={self.job_id}, "
            f"started_at={self.started_at}, ended_at={self.ended_at})>"
        )


class JobExpense(Base, WorkspaceScoped):
    """A single cost incurred while delivering a job."""

    __tablename__ = "job_expenses"
    __table_args__ = (Index("ix_job_expenses_workspace_job", "workspace_id", "job_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_service_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # Free-form grouping label (e.g. "materials", "fuel", "subcontractor").
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    incurred_on: Mapped[date | None] = mapped_column(DATE, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    job: Mapped["Job"] = relationship("Job")
    workspace: Mapped["Workspace"] = relationship("Workspace")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self) -> str:
        return f"<JobExpense(id={self.id}, job_id={self.job_id}, amount={self.amount})>"
