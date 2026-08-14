"""add manual quote deposit provenance

Revision ID: 20260813_manual_deposits
Revises: 6f50d2e7a9c1
Create Date: 2026-08-13 00:00:00.000000

Existing paid deposits came exclusively from Stripe, so the backfill can identify
them as card payments. New nullable provenance columns keep this migration safe
while the previous application version is still serving during deployment.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_manual_deposits"
down_revision: str | Sequence[str] | None = "6f50d2e7a9c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column("deposit_payment_method", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "quotes",
        sa.Column("deposit_recorded_by_id", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_quotes_deposit_payment_method",
        "quotes",
        "deposit_payment_method IN ('card', 'cash', 'check', 'other')",
    )
    op.create_foreign_key(
        "fk_quotes_deposit_recorded_by_id_users",
        "quotes",
        "users",
        ["deposit_recorded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "UPDATE quotes SET deposit_payment_method = 'card' "
        "WHERE deposit_paid_at IS NOT NULL AND deposit_payment_method IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_quotes_deposit_recorded_by_id_users",
        "quotes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_quotes_deposit_payment_method",
        "quotes",
        type_="check",
    )
    op.drop_column("quotes", "deposit_recorded_by_id")
    op.drop_column("quotes", "deposit_payment_method")
