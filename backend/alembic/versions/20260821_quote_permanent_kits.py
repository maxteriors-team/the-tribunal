"""Persist permanent-light kit selections on quotes.

Revision ID: 20260821_quote_permanent_kits
Revises: 20260821_comparison_complexity
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260821_quote_permanent_kits"
down_revision: str | None = "20260821_comparison_complexity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add server-written procurement metadata with an empty legacy default."""
    op.add_column(
        "quotes",
        sa.Column(
            "selected_permanent_kits",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Remove permanent-light procurement metadata."""
    op.drop_column("quotes", "selected_permanent_kits")
