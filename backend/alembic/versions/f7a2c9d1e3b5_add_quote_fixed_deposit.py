"""Add optional fixed-amount deposit to quotes.

Complements the existing percentage deposit (``21019f8d527d``): an operator can
now request either a percentage of the total *or* a fixed dollar amount. The
column is nullable/additive so existing quotes are unaffected; the effective
deposit is derived at read time (fixed preferred, clamped to the live total).

Revision ID: f7a2c9d1e3b5
Revises: d4945a5167e0
Create Date: 2026-07-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a2c9d1e3b5"
down_revision: str | None = "d4945a5167e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column("deposit_amount_fixed", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quotes", "deposit_amount_fixed")
