"""Retain the latest provider-accepted invoice email destination.

Revision ID: 20260825_invoice_email_snapshot
Revises: 20260826_bistro_allocs
Create Date: 2026-08-25

This is an expand-only rollout: both columns are nullable and require no backfill.
``last_emailed_to`` stores Fernet ciphertext through the model's
``EncryptedString`` type, whose database representation is ordinary ``TEXT``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_invoice_email_snapshot"
down_revision: str | None = "20260826_bistro_allocs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("last_emailed_to", sa.Text(), nullable=True))
    op.add_column(
        "invoices",
        sa.Column("last_emailed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoices", "last_emailed_at")
    op.drop_column("invoices", "last_emailed_to")
