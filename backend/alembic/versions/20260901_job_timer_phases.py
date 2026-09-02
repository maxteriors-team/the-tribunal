"""Add pause/end state to job time entries.

Revision ID: 20260901_job_timer_phases
Revises: 20260829_conversation_notes
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_job_timer_phases"
down_revision: str | None = "20260829_conversation_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DUPLICATE_OPEN_TIMERS = sa.text(
    """
    SELECT 1
    FROM job_time_entries
    WHERE ended_at IS NULL AND created_by_id IS NOT NULL
    GROUP BY workspace_id, job_id, created_by_id
    HAVING count(*) > 1
    LIMIT 1
    """
)


def upgrade() -> None:
    """Add timer stop state and enforce one active timer per user and job."""
    if op.get_bind().execute(_DUPLICATE_OPEN_TIMERS).first() is not None:
        raise RuntimeError(
            "Cannot enforce one active job timer: duplicate open entries exist for a user and job"
        )

    op.add_column("job_time_entries", sa.Column("stop_reason", sa.String(16), nullable=True))
    op.execute(
        """
        ALTER TABLE job_time_entries
        ADD CONSTRAINT ck_job_time_entries_stop_reason
        CHECK (
            stop_reason IS NULL OR
            (ended_at IS NOT NULL AND stop_reason IN ('paused', 'ended', 'manual'))
        ) NOT VALID
        """
    )
    op.execute("ALTER TABLE job_time_entries VALIDATE CONSTRAINT ck_job_time_entries_stop_reason")

    # Timer writes serialize on the job row, while this database guard closes the
    # remaining race window and protects direct/scripted writes.
    with op.get_context().autocommit_block():
        op.create_index(
            "uq_job_time_entries_open_creator",
            "job_time_entries",
            ["workspace_id", "job_id", "created_by_id"],
            unique=True,
            postgresql_where=sa.text("ended_at IS NULL AND created_by_id IS NOT NULL"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Remove timer stop state and the open-timer uniqueness guard."""
    with op.get_context().autocommit_block():
        op.drop_index(
            "uq_job_time_entries_open_creator",
            table_name="job_time_entries",
            postgresql_concurrently=True,
        )
    op.drop_constraint(op.f("ck_job_time_entries_stop_reason"), "job_time_entries", type_="check")
    op.drop_column("job_time_entries", "stop_reason")
