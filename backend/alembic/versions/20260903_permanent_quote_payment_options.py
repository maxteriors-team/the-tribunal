"""Add Permanent Lighting quote payment-option metadata.

Revision ID: 20260903_perm_payment_options
Revises: 20260903_technician_scoreboard
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260903_perm_payment_options"
down_revision: str | None = "20260903_technician_scoreboard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("quotes", sa.Column("payment_option", sa.String(length=20), nullable=True))
    op.add_column(
        "quotes",
        sa.Column(
            "permanent_pricing_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.create_check_constraint(
        "ck_quotes_payment_option",
        "quotes",
        "payment_option IN ('cash_check', 'financing')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_quotes_payment_option", "quotes", type_="check")
    op.drop_column("quotes", "permanent_pricing_snapshot")
    op.drop_column("quotes", "payment_option")
