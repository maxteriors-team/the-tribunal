"""Add opt-in inbound AI routing and disclosure audit fields.

All columns are additive. Existing phone numbers remain disabled, and existing
messages keep null disclosure fields. No customer communication data is read or
rewritten during the upgrade.

Revision ID: 20260829_inbound_ai_calls
Revises: 20260829_conversation_notes
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_inbound_ai_calls"
down_revision: str | None = "20260829_conversation_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DISCLOSURE_CHECK = "ck_messages_voice_disclosure_status"


def upgrade() -> None:
    """Add fail-closed inbound routing and nullable disclosure evidence."""
    op.add_column(
        "phone_numbers",
        sa.Column(
            "inbound_ai_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "phone_numbers",
        sa.Column("inbound_fallback_number", sa.Text(), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("voice_disclosure_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("voice_disclosure_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("voice_disclosed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        _DISCLOSURE_CHECK,
        "messages",
        "voice_disclosure_status IS NULL OR "
        "voice_disclosure_status IN ('pending', 'speaking', 'completed', 'failed')",
    )


def downgrade() -> None:
    """Remove inbound configuration and disclosure evidence.

    Downgrading after real calls loses the disclosure audit fields. Production
    rollback should therefore restore the pre-deploy backup instead of applying
    this downgrade after the feature has accepted callers.
    """
    op.drop_constraint(_DISCLOSURE_CHECK, "messages", type_="check")
    op.drop_column("messages", "voice_disclosed_at")
    op.drop_column("messages", "voice_disclosure_version")
    op.drop_column("messages", "voice_disclosure_status")
    op.drop_column("phone_numbers", "inbound_fallback_number")
    op.drop_column("phone_numbers", "inbound_ai_enabled")
