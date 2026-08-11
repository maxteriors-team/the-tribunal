"""add durable inbound message attachments

Revision ID: 20260811_message_attachments
Revises: 20260810_inv_optional
Create Date: 2026-08-11 00:00:01.000000

Signed Telnyx media URLs are queued here and copied to private object storage by
an in-process worker. The table is independent of contact records so media is
not lost when an inbound conversation has not yet been linked to a contact.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260811_message_attachments"
down_revision: str | Sequence[str] | None = "20260810_inv_optional"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_position", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("provider_content_type", sa.String(length=127), nullable=False),
        sa.Column("provider_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("provider_sha256", sa.String(length=64), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("content_type", sa.String(length=127), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name=op.f("ck_message_attachments_status"),
        ),
        sa.CheckConstraint(
            "provider_position >= 0",
            name=op.f("ck_message_attachments_provider_position_nonnegative"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_message_attachments_attempt_count_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_message_attachments_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_message_attachments_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_attachments")),
        sa.UniqueConstraint(
            "message_id",
            "provider_position",
            name="uq_message_attachments_message_position",
        ),
        sa.UniqueConstraint(
            "storage_key",
            name="uq_message_attachments_storage_key",
        ),
    )
    op.create_index(
        op.f("ix_message_attachments_workspace_id"),
        "message_attachments",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_message_attachments_message_id"),
        "message_attachments",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        "ix_message_attachments_queue",
        "message_attachments",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_message_attachments_queue", table_name="message_attachments")
    op.drop_index(op.f("ix_message_attachments_message_id"), table_name="message_attachments")
    op.drop_index(op.f("ix_message_attachments_workspace_id"), table_name="message_attachments")
    op.drop_table("message_attachments")
