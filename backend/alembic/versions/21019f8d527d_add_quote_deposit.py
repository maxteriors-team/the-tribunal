"""Add optional deposit to quotes (percentage + online-payment provenance).

Lets an operator request an upfront deposit (a percentage of the quote total)
that the client can pay online from the public proposal page via Stripe
Checkout. All columns are nullable/additive so existing quotes are unaffected;
the deposit amount is derived from the live total, never stored.

Revision ID: 21019f8d527d
Revises: f2a3b4c5d6e8
Create Date: 2026-07-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "21019f8d527d"
down_revision: str | None = "f2a3b4c5d6e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column("deposit_percentage", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "quotes",
        sa.Column("deposit_paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "quotes",
        sa.Column("deposit_checkout_session_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "quotes",
        sa.Column("deposit_payment_intent_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_quotes_deposit_checkout_session_id",
        "quotes",
        ["deposit_checkout_session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_quotes_deposit_checkout_session_id", table_name="quotes")
    op.drop_column("quotes", "deposit_payment_intent_id")
    op.drop_column("quotes", "deposit_checkout_session_id")
    op.drop_column("quotes", "deposit_paid_at")
    op.drop_column("quotes", "deposit_percentage")
