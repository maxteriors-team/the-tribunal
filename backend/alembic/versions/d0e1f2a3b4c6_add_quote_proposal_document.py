"""add quotes.proposal_document

Adds ``quotes.proposal_document``: a nullable JSONB snapshot of the sales
wizard's collected state (selected tiers, per-tier fixture lines, financing
terms, cash pricing, Care Plan choice, savings, add-ons). The canonical
``quote_line_items`` remain the trusted, server-computed totals for the accepted
headline tier; this column carries the richer multi-tier presentation the public
``/p/quotes/{token}`` page renders.

Additive and nullable \u2014 a quote created outside the wizard never sets it, so
existing rows are untouched and the change is fully reversible.

Revision ID: d0e1f2a3b4c6
Revises: c9d1e2f3a4b5
Create Date: 2026-07-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d0e1f2a3b4c6"
down_revision: Union[str, None] = "c9d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column(
            "proposal_document", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("quotes", "proposal_document")
