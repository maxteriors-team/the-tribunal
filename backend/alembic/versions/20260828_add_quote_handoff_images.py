"""Add private quote handoff images.

Revision ID: 20260828_handoff_images
Revises: 20260828_gable_pitch
Create Date: 2026-08-28

Expand-only: creates a dedicated table without modifying existing records.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260828_handoff_images"
down_revision: str | Sequence[str] | None = "20260828_gable_pitch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MAX_IMAGE_BYTES = 10 * 1024 * 1024


def upgrade() -> None:
    """Create the bounded, workspace-scoped handoff image table."""
    op.create_table(
        "quote_handoff_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_quote_handoff_images_content_type",
        ),
        sa.CheckConstraint(
            f"size_bytes > 0 AND size_bytes <= {_MAX_IMAGE_BYTES}",
            name="ck_quote_handoff_images_size",
        ),
        sa.CheckConstraint(
            "octet_length(data) = size_bytes",
            name="ck_quote_handoff_images_data_size",
        ),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name="fk_quote_handoff_images_quote_id_quotes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name="fk_quote_handoff_images_uploaded_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_quote_handoff_images_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quote_handoff_images"),
    )
    op.create_index(
        "ix_quote_handoff_images_workspace_quote_created",
        "quote_handoff_images",
        ["workspace_id", "quote_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop handoff images; production rollback requires backup or forward repair."""
    op.drop_index(
        "ix_quote_handoff_images_workspace_quote_created",
        table_name="quote_handoff_images",
    )
    op.drop_table("quote_handoff_images")
