"""Repair roofline proposal columns on databases stamped past their migration.

Revision ID: 20260822_roofline_repair
Revises: 20260821_browser_softphone
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_roofline_repair"
down_revision: str | None = "20260821_browser_softphone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "roofline_comparisons"
_PROPOSAL_SIDE_CHECK = "ck_roofline_comparisons_proposal_side"
_DISCOUNT_CHECK = "ck_roofline_comparisons_discount_amount_nonnegative"


def upgrade() -> None:
    """Add only proposal fields or constraints missing from this database.

    ``20260821_comparison_proposal`` already owns these objects for databases
    migrated from scratch. This repair exists for databases that were stamped
    past that revision before it entered their migration chain.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    check_sql = [
        str(constraint.get("sqltext") or "").lower()
        for constraint in inspector.get_check_constraints(_TABLE)
    ]

    if "proposal_side" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "proposal_side",
                sa.String(length=20),
                nullable=False,
                server_default="comparison",
            ),
        )
    if "discount_amount" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "discount_amount",
                sa.Numeric(precision=12, scale=2),
                nullable=False,
                server_default="0",
            ),
        )
    if not any("proposal_side" in sql for sql in check_sql):
        op.create_check_constraint(
            _PROPOSAL_SIDE_CHECK,
            _TABLE,
            "proposal_side IN ('permanent', 'seasonal', 'comparison')",
        )
    if not any("discount_amount" in sql for sql in check_sql):
        op.create_check_constraint(
            _DISCOUNT_CHECK,
            _TABLE,
            "discount_amount >= 0",
        )


def downgrade() -> None:
    """Keep shared columns owned by the earlier canonical migration.

    Dropping them here would corrupt databases where this repair was a no-op and
    ``20260821_comparison_proposal`` remains applied.
    """
