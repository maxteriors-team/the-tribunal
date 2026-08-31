"""Let a client decline a shared estimate

Two nullable columns on ``roofline_comparisons``. NULL means undecided, which is
what every existing row is, so no backfill and no default is needed and the add
is a metadata-only operation that does not rewrite the table.

The downgrade drops both columns, which discards any decline a client recorded.
That is the only reversible option here (the data has nowhere else to live), so
take a backup before downgrading if declines have been collected.

Revision ID: cc285c87ccd1
Revises: 0abbf756255f
Create Date: 2026-08-31 15:44:36.572931

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cc285c87ccd1"
down_revision: str | None = "0abbf756255f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "roofline_comparisons",
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "roofline_comparisons",
        sa.Column("decline_reason", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("roofline_comparisons", "decline_reason")
    op.drop_column("roofline_comparisons", "declined_at")
