"""Add internal time and attendance records and audits.

Revision ID: 20260820_time_attendance
Revises: 20260819_job_visits_pricing
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260820_time_attendance"
down_revision: str | Sequence[str] | None = "20260819_job_visits_pricing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

attendance_status = postgresql.ENUM(
    "open",
    "complete",
    "void",
    name="attendance_entry_status",
    create_type=False,
)
attendance_source = postgresql.ENUM(
    "clock",
    "manual",
    "admin",
    name="attendance_entry_source",
    create_type=False,
)


def upgrade() -> None:
    # UUID/int equality operators need GiST operator classes for interval exclusion.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    bind = op.get_bind()
    attendance_status.create(bind, checkfirst=True)
    attendance_source.create(bind, checkfirst=True)

    op.create_table(
        "attendance_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", attendance_status, nullable=False),
        sa.Column("source", attendance_source, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("clock_in_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("clock_out_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at",
            name="ck_attendance_entries_end_after_start",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND ended_at IS NULL) OR (status <> 'open' AND ended_at IS NOT NULL)",
            name="ck_attendance_entries_open_ended_consistency",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attendance_entries_workspace_user_started",
        "attendance_entries",
        ["workspace_id", "user_id", "started_at"],
    )
    op.create_index(
        "ix_attendance_entries_workspace_status_started",
        "attendance_entries",
        ["workspace_id", "status", "started_at"],
    )
    op.create_index(
        "uq_attendance_entries_open_user",
        "attendance_entries",
        ["workspace_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "uq_attendance_entries_clock_in_request",
        "attendance_entries",
        ["workspace_id", "clock_in_request_id"],
        unique=True,
        postgresql_where=sa.text("clock_in_request_id IS NOT NULL"),
    )
    op.create_index(
        "uq_attendance_entries_clock_out_request",
        "attendance_entries",
        ["workspace_id", "clock_out_request_id"],
        unique=True,
        postgresql_where=sa.text("clock_out_request_id IS NOT NULL"),
    )
    op.execute(
        """
        ALTER TABLE attendance_entries
        ADD CONSTRAINT excl_attendance_entries_nonvoid_overlap
        EXCLUDE USING gist (
            workspace_id WITH =,
            user_id WITH =,
            tstzrange(started_at, ended_at, '[)') WITH &&
        ) WHERE (status <> 'void'::attendance_entry_status)
        """
    )

    op.create_table(
        "attendance_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["attendance_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attendance_events_workspace_created",
        "attendance_events",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_attendance_events_entry_created",
        "attendance_events",
        ["entry_id", "created_at"],
    )
    op.create_index(
        "uq_attendance_events_workspace_request",
        "attendance_events",
        ["workspace_id", "request_id"],
        unique=True,
        postgresql_where=sa.text("request_id IS NOT NULL"),
    )

    op.create_table(
        "attendance_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("total_seconds", sa.BigInteger(), nullable=False),
        sa.Column("entry_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("end_date >= start_date", name="ck_attendance_exports_date_order"),
        sa.CheckConstraint("end_date - start_date <= 61", name="ck_attendance_exports_date_span"),
        sa.CheckConstraint("row_count >= 0", name="ck_attendance_exports_row_count_nonnegative"),
        sa.CheckConstraint("total_seconds >= 0", name="ck_attendance_exports_seconds_nonnegative"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_attendance_exports_sha256_length"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "request_id",
            name="uq_attendance_exports_workspace_request",
        ),
    )
    op.create_index(
        "ix_attendance_exports_workspace_created",
        "attendance_exports",
        ["workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("attendance_exports")
    op.drop_table("attendance_events")
    op.drop_table("attendance_entries")

    bind = op.get_bind()
    attendance_source.drop(bind, checkfirst=True)
    attendance_status.drop(bind, checkfirst=True)
    # btree_gist is shared infrastructure and intentionally remains installed.
