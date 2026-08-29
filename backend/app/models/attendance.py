"""Workspace-scoped time and attendance records and immutable audit rows."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    column,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

ATTENDANCE_STATUS_OPEN = "open"
ATTENDANCE_STATUS_COMPLETE = "complete"
ATTENDANCE_STATUS_VOID = "void"
ATTENDANCE_STATUSES = (
    ATTENDANCE_STATUS_OPEN,
    ATTENDANCE_STATUS_COMPLETE,
    ATTENDANCE_STATUS_VOID,
)

ATTENDANCE_SOURCE_CLOCK = "clock"
ATTENDANCE_SOURCE_MANUAL = "manual"
ATTENDANCE_SOURCE_ADMIN = "admin"
ATTENDANCE_SOURCES = (
    ATTENDANCE_SOURCE_CLOCK,
    ATTENDANCE_SOURCE_MANUAL,
    ATTENDANCE_SOURCE_ADMIN,
)

ATTENDANCE_PAUSE_END_RESUME = "resume"
ATTENDANCE_PAUSE_END_CLOCK_OUT = "clock_out"
ATTENDANCE_PAUSE_END_VOID = "void"
ATTENDANCE_PAUSE_END_ACTIONS = (
    ATTENDANCE_PAUSE_END_RESUME,
    ATTENDANCE_PAUSE_END_CLOCK_OUT,
    ATTENDANCE_PAUSE_END_VOID,
)

# Migrations own these PostgreSQL enum types. Keeping ORM values as strings makes
# service and schema boundaries straightforward while still validating writes.
_AttendanceStatusType = Enum(
    *ATTENDANCE_STATUSES,
    name="attendance_entry_status",
    create_type=False,
    native_enum=True,
    validate_strings=True,
)
_AttendanceSourceType = Enum(
    *ATTENDANCE_SOURCES,
    name="attendance_entry_source",
    create_type=False,
    native_enum=True,
    validate_strings=True,
)


class AttendanceEntry(Base, WorkspaceScoped):
    """One employee work interval; rows are corrected or voided, never deleted."""

    __tablename__ = "attendance_entries"
    __table_args__ = (
        CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at",
            name="ck_attendance_entries_end_after_start",
        ),
        CheckConstraint(
            "(status = 'open' AND ended_at IS NULL) OR (status <> 'open' AND ended_at IS NOT NULL)",
            name="ck_attendance_entries_open_ended_consistency",
        ),
        Index(
            "ix_attendance_entries_workspace_user_started",
            "workspace_id",
            "user_id",
            "started_at",
        ),
        Index(
            "ix_attendance_entries_workspace_status_started",
            "workspace_id",
            "status",
            "started_at",
        ),
        Index(
            "uq_attendance_entries_open_user",
            "workspace_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index(
            "uq_attendance_entries_clock_in_request",
            "workspace_id",
            "clock_in_request_id",
            unique=True,
            postgresql_where=text("clock_in_request_id IS NOT NULL"),
        ),
        Index(
            "uq_attendance_entries_clock_out_request",
            "workspace_id",
            "clock_out_request_id",
            unique=True,
            postgresql_where=text("clock_out_request_id IS NOT NULL"),
        ),
        ExcludeConstraint(
            (column("workspace_id"), "="),
            (column("user_id"), "="),
            (
                func.tstzrange(
                    column("started_at"),
                    column("ended_at"),
                    "[)",
                ),
                "&&",
            ),
            name="excl_attendance_entries_nonvoid_overlap",
            using="gist",
            where=text("status <> 'void'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        _AttendanceStatusType,
        nullable=False,
        default=ATTENDANCE_STATUS_OPEN,
    )
    source: Mapped[str] = mapped_column(
        _AttendanceSourceType,
        nullable=False,
        default=ATTENDANCE_SOURCE_CLOCK,
    )
    note: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    clock_in_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    clock_out_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
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
    pauses: Mapped[list[AttendancePause]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AttendancePause.started_at",
    )


class AttendancePause(Base):
    """A recorded non-working interval inside one clocked attendance entry."""

    __tablename__ = "attendance_pauses"
    __table_args__ = (
        CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at",
            name="ck_attendance_pauses_end_after_start",
        ),
        CheckConstraint(
            "(ended_at IS NULL AND end_request_id IS NULL AND end_action IS NULL) "
            "OR (ended_at IS NOT NULL AND end_request_id IS NOT NULL "
            "AND end_action IN ('resume', 'clock_out', 'void'))",
            name="ck_attendance_pauses_end_consistency",
        ),
        CheckConstraint(
            "end_request_id IS NULL OR end_request_id <> start_request_id",
            name="ck_attendance_pauses_distinct_requests",
        ),
        Index("ix_attendance_pauses_entry_started", "entry_id", "started_at"),
        Index(
            "uq_attendance_pauses_open_entry",
            "entry_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index(
            "uq_attendance_pauses_start_request",
            "start_request_id",
            unique=True,
        ),
        Index(
            "uq_attendance_pauses_end_request",
            "end_request_id",
            unique=True,
            postgresql_where=text("end_request_id IS NOT NULL"),
        ),
        ExcludeConstraint(
            (column("entry_id"), "="),
            (
                func.tstzrange(
                    column("started_at"),
                    column("ended_at"),
                    "[)",
                ),
                "&&",
            ),
            name="excl_attendance_pauses_overlap",
            using="gist",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    end_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    end_action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    entry: Mapped[AttendanceEntry] = relationship(back_populates="pauses")


class AttendanceEvent(Base, WorkspaceScoped):
    """Append-only audit event for an attendance mutation."""

    __tablename__ = "attendance_events"
    __table_args__ = (
        Index("ix_attendance_events_workspace_created", "workspace_id", "created_at"),
        Index("ix_attendance_events_entry_created", "entry_id", "created_at"),
        Index(
            "uq_attendance_events_workspace_request",
            "workspace_id",
            "request_id",
            unique=True,
            postgresql_where=text("request_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_entries.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    # Never place names, email addresses, notes, or reasons in this plaintext JSONB.
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class AttendanceExport(Base, WorkspaceScoped):
    """Audit metadata for an exported CSV; the CSV itself is never persisted."""

    __tablename__ = "attendance_exports"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "request_id",
            name="uq_attendance_exports_workspace_request",
        ),
        CheckConstraint("end_date >= start_date", name="ck_attendance_exports_date_order"),
        CheckConstraint("end_date - start_date <= 61", name="ck_attendance_exports_date_span"),
        CheckConstraint("row_count >= 0", name="ck_attendance_exports_row_count_nonnegative"),
        CheckConstraint("total_seconds >= 0", name="ck_attendance_exports_seconds_nonnegative"),
        CheckConstraint("char_length(sha256) = 64", name="ck_attendance_exports_sha256_length"),
        Index("ix_attendance_exports_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
