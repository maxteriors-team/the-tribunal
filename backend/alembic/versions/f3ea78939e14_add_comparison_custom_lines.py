"""Add standalone custom lines to a shared roofline comparison.

Stores the rep's ad-hoc estimate lines (label, quantity, unit price, side) as
inputs on the shared comparison, so the public page re-prices them alongside the
rest of the estimate. Nullable and additive: every already-shared link keeps its
current payload, which carries no custom lines at all.

Revision ID: f3ea78939e14
Revises: 75c8021514ac
Create Date: 2026-08-03 20:14:28.912093

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f3ea78939e14"
down_revision: str | None = "75c8021514ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "roofline_comparisons",
        sa.Column("custom_lines", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("roofline_comparisons", "custom_lines")
