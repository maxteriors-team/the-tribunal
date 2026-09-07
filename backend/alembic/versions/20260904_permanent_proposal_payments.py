"""Add immutable Permanent Lighting proposal payment evidence.

Revision ID: 20260904_proposal_payments
Revises: 20260903_technician_scoreboard
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260904_proposal_payments"
down_revision: str | Sequence[str] | None = "20260903_technician_scoreboard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quotes", sa.Column("proposal_payment_choice", sa.String(length=30), nullable=True)
    )
    op.add_column("quotes", sa.Column("proposal_payment_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column(
        "quotes",
        sa.Column("proposal_payment_checkout_session_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "quotes", sa.Column("proposal_payment_intent_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "quotes", sa.Column("proposal_payment_paid_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_quotes_proposal_payment_choice",
        "quotes",
        "proposal_payment_choice IN ('fifty_percent_down', 'pay_in_full')",
    )
    op.create_check_constraint(
        "ck_quotes_proposal_payment_amount_positive",
        "quotes",
        "proposal_payment_amount > 0",
    )
    op.create_check_constraint(
        "ck_quotes_proposal_payment_pair",
        "quotes",
        "(proposal_payment_choice IS NULL AND proposal_payment_amount IS NULL) OR "
        "(proposal_payment_choice IS NOT NULL AND proposal_payment_amount IS NOT NULL)",
    )
    op.create_index(
        "ix_quotes_proposal_payment_checkout_session_id",
        "quotes",
        ["proposal_payment_checkout_session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_quotes_proposal_payment_checkout_session_id", table_name="quotes")
    op.drop_constraint("ck_quotes_proposal_payment_pair", "quotes", type_="check")
    op.drop_constraint("ck_quotes_proposal_payment_amount_positive", "quotes", type_="check")
    op.drop_constraint("ck_quotes_proposal_payment_choice", "quotes", type_="check")
    op.drop_column("quotes", "proposal_payment_paid_at")
    op.drop_column("quotes", "proposal_payment_intent_id")
    op.drop_column("quotes", "proposal_payment_checkout_session_id")
    op.drop_column("quotes", "proposal_payment_amount")
    op.drop_column("quotes", "proposal_payment_choice")
