"""Add nullable source provenance to CRM conversations and messages.

Revision ID: 20260826_crm_provenance
Revises: 20260826_invoice_payments
Create Date: 2026-08-26

Expand-only upgrade: existing rows remain unchanged with NULL provenance.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_crm_provenance"
down_revision: str | None = "20260826_invoice_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("source_provider", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("source_provider", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("external_url", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "external_url")
    op.drop_column("messages", "source_provider")
    op.drop_column("conversations", "source_provider")
