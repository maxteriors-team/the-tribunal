"""add inbound_ring_operators to phone_numbers

Per-number opt-in to ringing logged-in operators' browsers before the existing
AI-answer / fallback-number inbound path runs. Defaults to false so no existing
number changes behaviour on deploy.

Revision ID: 6652913f227b
Revises: 20260909_seasonal_handoff
Create Date: 2026-09-10 20:33:53.679039

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6652913f227b"
down_revision: str | None = "20260909_seasonal_handoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "phone_numbers",
        sa.Column(
            "inbound_ring_operators",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("phone_numbers", "inbound_ring_operators")
