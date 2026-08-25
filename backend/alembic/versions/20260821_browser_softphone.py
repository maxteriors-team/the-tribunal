"""Add per-user Telnyx browser softphone identity.

Revision ID: 20260821_browser_softphone
Revises: 20260821_appointment_anytime
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_browser_softphone"
down_revision: str | None = "20260821_appointment_anytime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable provider identifiers without rewriting existing user rows."""
    op.add_column(
        "users",
        sa.Column("telnyx_telephony_credential_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("telnyx_sip_username", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_users_telnyx_telephony_credential_id",
        "users",
        ["telnyx_telephony_credential_id"],
        unique=True,
    )
    op.create_index(
        "ix_users_telnyx_sip_username",
        "users",
        ["telnyx_sip_username"],
        unique=True,
    )


def downgrade() -> None:
    """Remove browser softphone identity without touching user profile data."""
    op.drop_index("ix_users_telnyx_sip_username", table_name="users")
    op.drop_index("ix_users_telnyx_telephony_credential_id", table_name="users")
    op.drop_column("users", "telnyx_sip_username")
    op.drop_column("users", "telnyx_telephony_credential_id")
