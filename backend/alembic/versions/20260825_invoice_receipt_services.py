"""Snapshot service names for paid-invoice receipt emails.

Revision ID: 20260825_receipt_services
Revises: 20260825_invoice_receipt_outbox
Create Date: 2026-08-25

The encrypted snapshot is nullable so already-queued receipts remain deliverable.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_receipt_services"
down_revision: str | None = "20260825_invoice_receipt_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invoice_payment_receipt_outbox",
        sa.Column("service_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoice_payment_receipt_outbox", "service_summary")
