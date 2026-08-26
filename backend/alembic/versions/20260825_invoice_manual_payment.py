"""Record cash/check invoice settlement provenance.

Revision ID: 20260825_invoice_manual_pay
Revises: 20260825_receipt_services
Create Date: 2026-08-25

The migration is additive. Existing paid invoices are labelled as card-settled because
manual invoice settlement did not exist before this revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260825_invoice_manual_pay"
down_revision: str | None = "20260825_receipt_services"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("payment_method", sa.String(length=20), nullable=True))
    op.add_column(
        "invoices",
        sa.Column("payment_recorded_by_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("manual_payment_amount", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("manual_payment_reference", sa.Text(), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column(
            "manual_payment_idempotency_key",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_invoices_payment_method",
        "invoices",
        "payment_method IN ('card', 'cash', 'check')",
    )
    op.create_check_constraint(
        "ck_invoices_manual_payment_amount",
        "invoices",
        "manual_payment_amount IS NULL OR manual_payment_amount > 0",
    )
    op.create_unique_constraint(
        "uq_invoices_manual_payment_idempotency_key",
        "invoices",
        ["manual_payment_idempotency_key"],
    )
    op.create_foreign_key(
        "fk_invoices_payment_recorded_by_id_users",
        "invoices",
        "users",
        ["payment_recorded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("UPDATE invoices SET payment_method = 'card' WHERE paid_at IS NOT NULL")


def downgrade() -> None:
    op.drop_constraint("fk_invoices_payment_recorded_by_id_users", "invoices", type_="foreignkey")
    op.drop_constraint(
        "uq_invoices_manual_payment_idempotency_key",
        "invoices",
        type_="unique",
    )
    op.drop_constraint("ck_invoices_manual_payment_amount", "invoices", type_="check")
    op.drop_constraint("ck_invoices_payment_method", "invoices", type_="check")
    op.drop_column("invoices", "manual_payment_idempotency_key")
    op.drop_column("invoices", "manual_payment_reference")
    op.drop_column("invoices", "manual_payment_amount")
    op.drop_column("invoices", "payment_recorded_by_id")
    op.drop_column("invoices", "payment_method")
