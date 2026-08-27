"""Add persisted SMS booking confirmation drafts.

Revision ID: 20260826_sms_drafts
Revises: 20260826_quo_inbox
Create Date: 2026-08-26

Expand-only: creates an independent table. Existing conversations and messages
are not rewritten. Email and confirmation text are Fernet ciphertext stored in
ordinary TEXT columns by the ORM.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_sms_drafts"
down_revision: str | Sequence[str] | None = "20260826_quo_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one complete, workspace-scoped draft per conversation."""
    op.create_table(
        "conversation_booking_drafts",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("time", sa.Time(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("call_type", sa.String(length=20), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("confirmation_text", sa.Text(), nullable=False),
        sa.Column(
            "prepared_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 5 AND 480",
            name="ck_conversation_booking_drafts_duration",
        ),
        sa.CheckConstraint(
            "call_type IN ('phone_call', 'video_call')",
            name="ck_conversation_booking_drafts_call_type",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_conversation_booking_drafts_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_conversation_booking_drafts_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "conversation_id",
            name="pk_conversation_booking_drafts",
        ),
    )
    op.create_index(
        "ix_conversation_booking_drafts_workspace_id",
        "conversation_booking_drafts",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only pending drafts; booked appointments remain untouched."""
    op.drop_index(
        "ix_conversation_booking_drafts_workspace_id",
        table_name="conversation_booking_drafts",
    )
    op.drop_table("conversation_booking_drafts")
