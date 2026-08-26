"""Scope manual-payment idempotency keys per workspace.

Revision ID: 20260825_manual_pay_scope
Revises: 20260825_invoice_manual_pay
Create Date: 2026-08-25

This follow-up preserves tenant isolation and clears the temporary card label from
historical paid invoices that have no Stripe payment intent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260825_manual_pay_scope"
down_revision: str | None = "20260825_invoice_manual_pay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_invoices_manual_payment_idempotency_key",
        "invoices",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_invoices_manual_payment_idempotency_key",
        "invoices",
        ["workspace_id", "manual_payment_idempotency_key"],
    )
    op.execute(
        "UPDATE invoices SET payment_method = NULL "
        "WHERE payment_method = 'card' "
        "AND stripe_payment_intent_id IS NULL "
        "AND manual_payment_idempotency_key IS NULL"
    )


def downgrade() -> None:
    # The old global constraint cannot represent legitimate cross-workspace key
    # reuse. Preserve every payment row while assigning fresh keys to duplicates.
    op.execute(
        "WITH ranked AS ("
        "SELECT id, ROW_NUMBER() OVER ("
        "PARTITION BY manual_payment_idempotency_key ORDER BY id"
        ") AS occurrence FROM invoices "
        "WHERE manual_payment_idempotency_key IS NOT NULL"
        ") UPDATE invoices AS invoice "
        "SET manual_payment_idempotency_key = gen_random_uuid() "
        "FROM ranked WHERE invoice.id = ranked.id AND ranked.occurrence > 1"
    )
    op.drop_constraint(
        "uq_invoices_manual_payment_idempotency_key",
        "invoices",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_invoices_manual_payment_idempotency_key",
        "invoices",
        ["manual_payment_idempotency_key"],
    )
    op.execute("UPDATE invoices SET payment_method = 'card' WHERE paid_at IS NOT NULL")
