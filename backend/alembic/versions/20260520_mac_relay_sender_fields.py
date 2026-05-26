"""add mac relay sender fields

Revision ID: 20260520_mac_relay_sender_fields
Revises: 20260519_outbound_compliance
Create Date: 2026-05-20 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260520_mac_relay_sender_fields"
down_revision: str | Sequence[str] | None = "20260519_outbound_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "phone_numbers",
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="telnyx"),
    )
    op.add_column(
        "phone_numbers",
        sa.Column("imessage_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "phone_numbers",
        sa.Column("mac_relay_sender_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "phone_numbers",
        sa.Column(
            "mac_relay_service",
            sa.String(length=20),
            nullable=False,
            server_default="imessage",
        ),
    )

    op.create_index("ix_phone_numbers_provider", "phone_numbers", ["provider"])
    op.create_index(
        "ix_phone_numbers_workspace_imessage_enabled",
        "phone_numbers",
        ["workspace_id", "imessage_enabled"],
    )
    op.create_index(
        "ix_phone_numbers_mac_relay_sender_id",
        "phone_numbers",
        ["mac_relay_sender_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_phone_numbers_mac_relay_sender_id", table_name="phone_numbers")
    op.drop_index("ix_phone_numbers_workspace_imessage_enabled", table_name="phone_numbers")
    op.drop_index("ix_phone_numbers_provider", table_name="phone_numbers")

    op.drop_column("phone_numbers", "mac_relay_service")
    op.drop_column("phone_numbers", "mac_relay_sender_id")
    op.drop_column("phone_numbers", "imessage_enabled")
    op.drop_column("phone_numbers", "provider")
