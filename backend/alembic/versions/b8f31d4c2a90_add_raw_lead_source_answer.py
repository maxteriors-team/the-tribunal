"""add raw lead source answer

Revision ID: b8f31d4c2a90
Revises: 794de67ae8c8
Create Date: 2026-07-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8f31d4c2a90"
down_revision: str | None = "794de67ae8c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store the verbatim AI receptionist answer separately from legacy source."""
    op.add_column("contacts", sa.Column("lead_source_raw_answer", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove the raw receptionist answer field."""
    op.drop_column("contacts", "lead_source_raw_answer")
