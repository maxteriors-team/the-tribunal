"""Allow appointments without a specific start time.

Revision ID: 20260821_appointment_anytime
Revises: 20260821_comparison_proposal
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_appointment_anytime"
down_revision: str | None = "20260821_comparison_proposal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a metadata-only default so existing appointments stay timed."""
    op.add_column(
        "appointments",
        sa.Column("anytime", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    """Remove the anytime marker without changing appointment datetimes."""
    op.drop_column("appointments", "anytime")
