"""Add seen_webhook_signatures ledger for webhook replay rejection.

Revision ID: b2d5f8a1c034
Revises: a1c4e7f09b23
Create Date: 2026-07-28 12:00:00.000000

Cal.com signs the raw request body only, so a captured
``(body, x-cal-signature-256)`` pair verifies forever and no header-based
freshness check can close that window (Cal.com sends no timestamp, and any
timestamp we did honour would be unsigned and forgeable). The durable fix is to
remember which signatures we have already accepted.

This table is that ledger. ``(provider, signature)`` is UNIQUE; the claim path
inserts with ``ON CONFLICT DO NOTHING`` and treats "no row inserted" as a replay.
``created_at`` backs the retention sweep in
``app/workers/webhook_signature_cleanup_worker.py``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d5f8a1c034"
down_revision: str | None = "a1c4e7f09b23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "seen_webhook_signatures"
UNIQUE_NAME = "uq_seen_webhook_signatures_provider_signature"
INDEX_NAME = "ix_seen_webhook_signatures_created_at"


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("signature", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("provider", "signature", name=UNIQUE_NAME),
    )
    # Backs the retention sweep's indexed range delete.
    op.create_index(INDEX_NAME, TABLE_NAME, ["created_at"])


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
