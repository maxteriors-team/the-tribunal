"""add encrypted agent training examples

Revision ID: 20260812_training_examples
Revises: 20260811_lighting_handoff
Create Date: 2026-08-12 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260812_training_examples"
down_revision: str | Sequence[str] | None = "20260811_lighting_handoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_training_examples",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        # EncryptedString persists Fernet ciphertext in ordinary TEXT columns.
        sa.Column("customer_message", sa.Text(), nullable=False),
        sa.Column("ai_response", sa.Text(), nullable=False),
        sa.Column("ideal_response", sa.Text(), nullable=False),
        sa.Column("operator_note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_message_id", name="uq_agent_training_examples_source_message_id"
        ),
    )
    op.create_index(
        "ix_agent_training_examples_workspace_agent_active_created",
        "agent_training_examples",
        ["workspace_id", "agent_id", "is_active", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_training_examples_workspace_agent_active_created",
        table_name="agent_training_examples",
    )
    op.drop_table("agent_training_examples")
