"""Add Quo voice timeline metadata.

Revision ID: 20260826_quo_voice
Revises: 20260826_crm_provenance
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_quo_voice"
down_revision: str | Sequence[str] | None = "20260826_crm_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an expand-only voicemail indicator without rewriting existing rows."""
    op.add_column(
        "messages",
        sa.Column(
            "is_voicemail",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the Quo voicemail indicator."""
    op.drop_column("messages", "is_voicemail")
