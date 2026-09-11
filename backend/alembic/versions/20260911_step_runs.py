"""Add the per-step ledger for workflow runs.

``automation_executions.step_index`` says how far a run got. It cannot say what
happened along the way: a cursor reading 7 might mean three messages sent and
four skipped on consent. ``unsold_quote_worker`` keeps that ledger by hand in
``quote_followup_touches`` precisely because the engine had nowhere to put it.

Append-only by design — a backward goto may revisit a step, and each visit is
its own row, so there is no unique constraint on (execution_id, step_index).
Collapsing them would erase the evidence that a workflow is looping.

Revision ID: 20260911_step_runs
Revises: 20260911_execution_subject
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260911_step_runs"
down_revision: str | None = "20260911_execution_subject"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automation_step_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.String(length=64), nullable=True),
        sa.Column("step_type", sa.String(length=50), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["automation_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_automation_step_runs_workspace_id",
        "automation_step_runs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_automation_step_runs_execution_id",
        "automation_step_runs",
        ["execution_id"],
    )
    op.create_index(
        "ix_automation_step_runs_automation_id",
        "automation_step_runs",
        ["automation_id"],
    )
    # "What happened in this run, in order" — also the last-touch query.
    op.create_index(
        "ix_automation_step_runs_execution_created",
        "automation_step_runs",
        ["execution_id", "created_at"],
    )
    # Per-automation reporting slice.
    op.create_index(
        "ix_automation_step_runs_automation_created",
        "automation_step_runs",
        ["automation_id", "created_at"],
    )
    # Frequency capping: when did we last touch this person, across sequences.
    op.create_index(
        "ix_automation_step_runs_contact_created",
        "automation_step_runs",
        ["contact_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_automation_step_runs_contact_created", table_name="automation_step_runs")
    op.drop_index("ix_automation_step_runs_automation_created", table_name="automation_step_runs")
    op.drop_index("ix_automation_step_runs_execution_created", table_name="automation_step_runs")
    op.drop_index("ix_automation_step_runs_automation_id", table_name="automation_step_runs")
    op.drop_index("ix_automation_step_runs_execution_id", table_name="automation_step_runs")
    op.drop_index("ix_automation_step_runs_workspace_id", table_name="automation_step_runs")
    op.drop_table("automation_step_runs")
