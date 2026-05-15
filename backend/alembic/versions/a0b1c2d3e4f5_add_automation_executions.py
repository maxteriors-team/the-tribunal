"""add_automation_executions

Adds the automation_executions table that tracks which contacts have been
processed by each automation, preventing duplicate execution.

Also adds last_evaluated_at column to automations so the worker can query
contacts updated since the last evaluation cycle.

Revision ID: a0b1c2d3e4f5
Revises: z8a9b0c1d2e3
Create Date: 2025-03-19 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a0b1c2d3e4f5"
down_revision: str | None = "z8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add last_evaluated_at to automations
    op.add_column(
        "automations",
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Create automation_executions table
    op.create_table(
        "automation_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["automation_id"],
            ["automations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "automation_id",
            "contact_id",
            name="uq_automation_execution",
        ),
    )
    op.create_index(
        "ix_automation_executions_automation_id",
        "automation_executions",
        ["automation_id"],
    )
    op.create_index(
        "ix_automation_executions_contact_id",
        "automation_executions",
        ["contact_id"],
    )
    op.create_index(
        "ix_automation_executions_status",
        "automation_executions",
        ["status"],
    )
    op.create_index(
        "ix_automation_executions_scheduled_for",
        "automation_executions",
        ["scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_automation_executions_scheduled_for",
        table_name="automation_executions",
    )
    op.drop_index(
        "ix_automation_executions_status",
        table_name="automation_executions",
    )
    op.drop_index(
        "ix_automation_executions_contact_id",
        table_name="automation_executions",
    )
    op.drop_index(
        "ix_automation_executions_automation_id",
        table_name="automation_executions",
    )
    op.drop_table("automation_executions")
    op.drop_column("automations", "last_evaluated_at")
