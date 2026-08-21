"""Persist the selected proposal side and discount on shared estimates.

Revision ID: 20260821_comparison_proposal
Revises: 20260821_quote_permanent_kits
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_comparison_proposal"
down_revision: str | None = "20260821_quote_permanent_kits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add server-validated customer proposal context to saved comparisons."""
    op.add_column(
        "roofline_comparisons",
        sa.Column(
            "proposal_side",
            sa.String(length=20),
            nullable=False,
            server_default="comparison",
        ),
    )
    op.add_column(
        "roofline_comparisons",
        sa.Column(
            "discount_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_roofline_comparisons_proposal_side",
        "roofline_comparisons",
        "proposal_side IN ('permanent', 'seasonal', 'comparison')",
    )
    op.create_check_constraint(
        "ck_roofline_comparisons_discount_amount_nonnegative",
        "roofline_comparisons",
        "discount_amount >= 0",
    )


def downgrade() -> None:
    """Remove customer proposal context from shared comparisons."""
    op.drop_constraint(
        "ck_roofline_comparisons_discount_amount_nonnegative",
        "roofline_comparisons",
        type_="check",
    )
    op.drop_constraint(
        "ck_roofline_comparisons_proposal_side",
        "roofline_comparisons",
        type_="check",
    )
    op.drop_column("roofline_comparisons", "discount_amount")
    op.drop_column("roofline_comparisons", "proposal_side")
