"""add quote followup touch ledger

Revision ID: 9316dc32e25b
Revises: b8f31d4c2a90
Create Date: 2026-07-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9316dc32e25b"
down_revision: str | None = "b8f31d4c2a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the idempotent per-quote cadence execution ledger."""
    op.create_table(
        "quote_followup_touches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offset_days", sa.Integer(), nullable=False),
        sa.Column("configured_channel", sa.String(length=20), nullable=False),
        sa.Column("delivered_channel", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=True),
        sa.Column("message_template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("human_nudge_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_template_id"],
            ["message_templates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["human_nudge_id"],
            ["human_nudges.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "quote_id",
            "offset_days",
            name="uq_quote_followup_touches_quote_offset",
        ),
    )
    op.create_index(
        op.f("ix_quote_followup_touches_quote_id"),
        "quote_followup_touches",
        ["quote_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quote_followup_touches_workspace_id"),
        "quote_followup_touches",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_quote_followup_touches_workspace_processed",
        "quote_followup_touches",
        ["workspace_id", "processed_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the quote follow-up execution ledger."""
    op.drop_index(
        "ix_quote_followup_touches_workspace_processed",
        table_name="quote_followup_touches",
    )
    op.drop_index(
        op.f("ix_quote_followup_touches_workspace_id"),
        table_name="quote_followup_touches",
    )
    op.drop_index(
        op.f("ix_quote_followup_touches_quote_id"),
        table_name="quote_followup_touches",
    )
    op.drop_table("quote_followup_touches")
