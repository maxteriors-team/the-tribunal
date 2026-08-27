"""Add durable message sender attribution.

Revision ID: 20260826_msg_sender
Revises: 20260826_sms_drafts
Create Date: 2026-08-26

Expand-only: adds nullable columns without rewriting or guessing historical rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_msg_sender"
down_revision: str | Sequence[str] | None = "20260826_sms_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SENDER_USER_FK = "fk_messages_sender_user_id_users"


def upgrade() -> None:
    """Add nullable sender identity and immutable display-name snapshots."""
    op.add_column("messages", sa.Column("sender_user_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "messages",
        sa.Column("sender_display_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("provider_sender_user_id", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        _SENDER_USER_FK,
        "messages",
        "users",
        ["sender_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Remove only sender-attribution fields; prefer forward repair in production."""
    op.drop_constraint(_SENDER_USER_FK, "messages", type_="foreignkey")
    op.drop_column("messages", "provider_sender_user_id")
    op.drop_column("messages", "sender_display_name")
    op.drop_column("messages", "sender_user_id")
