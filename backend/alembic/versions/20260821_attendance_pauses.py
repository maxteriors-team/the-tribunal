"""Add auditable pause intervals to attendance entries.

Revision ID: 20260821_attendance_pauses
Revises: 20260820_time_attendance
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260821_attendance_pauses"
down_revision: str | Sequence[str] | None = "20260820_time_attendance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attendance_pauses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("end_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("end_action", sa.String(length=20), nullable=True),
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
            name="ck_attendance_pauses_end_after_start",
        ),
        sa.CheckConstraint(
            "(ended_at IS NULL AND end_request_id IS NULL AND end_action IS NULL) "
            "OR (ended_at IS NOT NULL AND end_request_id IS NOT NULL "
            "AND end_action IN ('resume', 'clock_out', 'void'))",
            name="ck_attendance_pauses_end_consistency",
        ),
        sa.CheckConstraint(
            "end_request_id IS NULL OR end_request_id <> start_request_id",
            name="ck_attendance_pauses_distinct_requests",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["attendance_entries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        postgresql.ExcludeConstraint(
            (sa.column("entry_id"), "="),
            (
                sa.func.tstzrange(
                    sa.column("started_at"),
                    sa.column("ended_at"),
                    "[)",
                ),
                "&&",
            ),
            name="excl_attendance_pauses_overlap",
            using="gist",
        ),
    )
    op.create_index(
        "ix_attendance_pauses_entry_started",
        "attendance_pauses",
        ["entry_id", "started_at"],
    )
    op.create_index(
        "uq_attendance_pauses_open_entry",
        "attendance_pauses",
        ["entry_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        "uq_attendance_pauses_start_request",
        "attendance_pauses",
        ["start_request_id"],
        unique=True,
    )
    op.create_index(
        "uq_attendance_pauses_end_request",
        "attendance_pauses",
        ["end_request_id"],
        unique=True,
        postgresql_where=sa.text("end_request_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION validate_attendance_pause_bounds() RETURNS trigger AS $$
        DECLARE
            parent attendance_entries%ROWTYPE;
        BEGIN
            SELECT * INTO parent FROM attendance_entries WHERE id = NEW.entry_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'attendance entry % does not exist', NEW.entry_id;
            END IF;
            IF parent.source <> 'clock'::attendance_entry_source THEN
                RAISE EXCEPTION 'only clock-sourced attendance entries may be paused';
            END IF;
            IF NEW.started_at < parent.started_at
               OR (
                   parent.ended_at IS NOT NULL
                   AND (NEW.ended_at IS NULL OR NEW.ended_at > parent.ended_at)
               )
               OR (
                   parent.status <> 'open'::attendance_entry_status
                   AND NEW.ended_at IS NULL
               ) THEN
                RAISE EXCEPTION 'attendance pause must be contained by its entry';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_attendance_pause_bounds
        BEFORE INSERT OR UPDATE ON attendance_pauses
        FOR EACH ROW EXECUTE FUNCTION validate_attendance_pause_bounds()
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_attendance_entry_pauses() RETURNS trigger AS $$
        DECLARE
            current_entry attendance_entries%ROWTYPE;
        BEGIN
            SELECT * INTO current_entry FROM attendance_entries WHERE id = NEW.id;
            IF NOT FOUND THEN
                RETURN NEW;
            END IF;
            IF EXISTS (
                SELECT 1
                FROM attendance_pauses pause
                WHERE pause.entry_id = current_entry.id
                  AND (
                      pause.started_at < current_entry.started_at
                      OR (
                          current_entry.ended_at IS NOT NULL
                          AND (pause.ended_at IS NULL OR pause.ended_at > current_entry.ended_at)
                      )
                      OR (
                          current_entry.status <> 'open'::attendance_entry_status
                          AND pause.ended_at IS NULL
                      )
                  )
            ) THEN
                RAISE EXCEPTION 'attendance entry must contain all of its pauses';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_attendance_entry_pause_bounds
        AFTER UPDATE OF started_at, ended_at, status ON attendance_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_attendance_entry_pauses()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_attendance_entry_pause_bounds ON attendance_entries"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_attendance_pause_bounds ON attendance_pauses")
    op.execute("DROP FUNCTION IF EXISTS validate_attendance_entry_pauses()")
    op.execute("DROP FUNCTION IF EXISTS validate_attendance_pause_bounds()")
    op.drop_table("attendance_pauses")
