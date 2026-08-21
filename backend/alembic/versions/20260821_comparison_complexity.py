"""Persist permanent-light complexity on shared comparisons.

Revision ID: 20260821_comparison_complexity
Revises: 20260821_attendance_pauses
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260821_comparison_complexity"
down_revision: str | None = "20260821_attendance_pauses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COMPLEXITY_CHECK = "permanent_complexity IN ('aerial', 'easy', 'standard', 'complex')"
_COMPLEXITY_CHECK_NAME = "ck_roofline_comparisons_permanent_complexity"


def upgrade() -> None:
    """Keep old shares Standard while retaining new per-run complexity inputs."""
    op.add_column(
        "roofline_comparisons",
        sa.Column(
            "permanent_complexity",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'standard'"),
        ),
    )
    op.add_column(
        "roofline_comparisons",
        sa.Column(
            "permanent_complexity_feet", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.create_check_constraint(
        _COMPLEXITY_CHECK_NAME,
        "roofline_comparisons",
        _COMPLEXITY_CHECK,
    )


def downgrade() -> None:
    """Remove persisted complexity while preserving the legacy comparison shape."""
    op.drop_constraint(_COMPLEXITY_CHECK_NAME, "roofline_comparisons", type_="check")
    op.drop_column("roofline_comparisons", "permanent_complexity_feet")
    op.drop_column("roofline_comparisons", "permanent_complexity")
