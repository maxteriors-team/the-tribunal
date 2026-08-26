"""Add append-only invoice payments and partial-receipt balances.

Revision ID: 20260826_invoice_payments
Revises: 20260825_manual_pay_scope
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_invoice_payments"
down_revision: str | None = "20260825_manual_pay_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoice_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_method", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("recorded_by_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_event_id", sa.String(length=255), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "payment_method IN ('card', 'cash', 'check', 'other')",
            name="ck_invoice_payments_method",
        ),
        sa.CheckConstraint("amount > 0", name="ck_invoice_payments_amount_positive"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_invoice_payments_workspace_idempotency",
        ),
        sa.UniqueConstraint(
            "external_event_id",
            name="uq_invoice_payments_external_event",
        ),
    )
    op.create_index(
        "ix_invoice_payments_workspace_invoice",
        "invoice_payments",
        ["workspace_id", "invoice_id"],
        unique=False,
    )
    op.execute(
        "INSERT INTO invoice_payments ("
        "id, workspace_id, invoice_id, payment_method, amount, reference, "
        "recorded_by_id, idempotency_key, external_event_id, received_at, "
        "created_at, updated_at"
        ") SELECT gen_random_uuid(), workspace_id, id, "
        "COALESCE(payment_method, 'other'), amount_paid, manual_payment_reference, "
        "payment_recorded_by_id, manual_payment_idempotency_key, external_event_id, "
        "COALESCE(paid_at, updated_at, created_at), created_at, updated_at FROM ("
        "SELECT invoices.*, CASE WHEN stripe_payment_intent_id IS NOT NULL AND "
        "ROW_NUMBER() OVER (PARTITION BY stripe_payment_intent_id "
        "ORDER BY created_at, id) = 1 THEN stripe_payment_intent_id ELSE NULL END "
        "AS external_event_id FROM invoices WHERE amount_paid > 0"
        ") AS backfill"
    )
    op.add_column(
        "invoice_payment_receipt_outbox",
        sa.Column("balance_remaining", sa.Numeric(precision=12, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoice_payment_receipt_outbox", "balance_remaining")
    op.drop_index(
        "ix_invoice_payments_workspace_invoice",
        table_name="invoice_payments",
    )
    op.drop_table("invoice_payments")
