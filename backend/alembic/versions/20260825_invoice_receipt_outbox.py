"""Add the transactional paid-invoice receipt outbox.

Revision ID: 20260825_invoice_receipt_outbox
Revises: 20260825_invoice_email_snapshot
Create Date: 2026-08-25

Expand-only: this creates an independent table and indexes; no existing rows are
rewritten and no application column is removed or made stricter.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260825_invoice_receipt_outbox"
down_revision: str | None = "20260825_invoice_email_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoice_payment_receipt_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_event_id", sa.String(length=255), nullable=False),
        sa.Column("recipient_email", sa.Text(), nullable=True),
        sa.Column("customer_name", sa.Text(), nullable=False),
        sa.Column("business_name", sa.String(length=255), nullable=False),
        sa.Column("invoice_number", sa.String(length=100), nullable=False),
        sa.Column("payment_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("invoice_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_paid", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("support_email", sa.Text(), nullable=True),
        sa.Column("support_phone", sa.Text(), nullable=True),
        sa.Column("invoice_url", sa.Text(), nullable=True),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 5",
            name="ck_invoice_payment_receipt_outbox_attempt_count",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'terminal')",
            name="ck_invoice_payment_receipt_outbox_status",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name="fk_invoice_receipt_outbox_invoice",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_invoice_receipt_outbox_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_payment_receipt_outbox"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_invoice_payment_receipt_outbox_idempotency_key",
        ),
        sa.UniqueConstraint(
            "invoice_id",
            "payment_event_id",
            name="uq_invoice_receipt_outbox_invoice_event",
        ),
    )
    op.create_index(
        "ix_invoice_payment_receipt_outbox_workspace_id",
        "invoice_payment_receipt_outbox",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_invoice_receipt_outbox_due",
        "invoice_payment_receipt_outbox",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_invoice_receipt_outbox_due",
        table_name="invoice_payment_receipt_outbox",
    )
    op.drop_index(
        "ix_invoice_payment_receipt_outbox_workspace_id",
        table_name="invoice_payment_receipt_outbox",
    )
    op.drop_table("invoice_payment_receipt_outbox")
