"""repair opportunity tasks skipped by a reparented migration

Revision ID: 20260813_repair_tasks
Revises: 20260813_manual_deposits
Create Date: 2026-08-13 23:50:00.000000

``3c451b655d90`` was reparented after some databases had already applied it.
Alembic therefore considers its new parent, ``20260812_opportunity_tasks``, part
of those databases' history without ever running that parent's upgrade. Fresh
databases already have this table; upgraded databases may not. Idempotent DDL
repairs both states without touching existing opportunity rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_repair_tasks"
down_revision: str | Sequence[str] | None = "20260813_manual_deposits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "opportunity_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_id", sa.Integer(), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_user_id"],
            ["users.id"],
            name=op.f("fk_opportunity_tasks_assigned_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_id"],
            ["users.id"],
            name=op.f("fk_opportunity_tasks_completed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_opportunity_tasks_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_opportunity_tasks_opportunity_id_opportunities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunity_tasks")),
        if_not_exists=True,
    )
    op.create_index(
        op.f("ix_opportunity_tasks_assigned_user_id"),
        "opportunity_tasks",
        ["assigned_user_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        op.f("ix_opportunity_tasks_completed_at"),
        "opportunity_tasks",
        ["completed_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        op.f("ix_opportunity_tasks_due_at"),
        "opportunity_tasks",
        ["due_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        op.f("ix_opportunity_tasks_opportunity_id"),
        "opportunity_tasks",
        ["opportunity_id"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    # The canonical 20260812 migration owns this table's lifetime. Keeping it on
    # a one-step downgrade restores the schema that revision intended; a deeper
    # downgrade runs that canonical migration's drop operations.
    pass
