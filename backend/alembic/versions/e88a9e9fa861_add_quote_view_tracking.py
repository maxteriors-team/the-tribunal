"""Track when a client opens their public proposal.

Revision ID: e88a9e9fa861
Revises: b3f1c7d92a04
Create Date: 2026-08-03 16:24:40.607115

Until now ``GET /api/v1/p/quotes/{token}`` was a pure read and nothing was
recorded, so an operator had no way to know a customer was looking at their
proposal — the single best moment to pick up the phone.

Three additive columns on ``quotes`` carry that signal:

- ``first_viewed_at`` — first genuine client view, never overwritten.
- ``last_viewed_at``  — most recent view; drives "opened 10 minutes ago".
- ``view_count``      — *throttled* views (repeats inside the service's
  ``VIEW_THROTTLE_MINUTES`` window don't increment), so a customer leaving a
  tab open doesn't read as forty visits.

Safe on live data: two nullable timestamptz columns plus one NOT NULL integer
landing with a ``'0'`` server default — no table rewrite, no downtime.

**No backfill is possible or meaningful.** A view is an event that was never
captured before this migration, so existing quotes correctly read as
never-viewed rather than as viewed-at-an-invented-time. Inventing a timestamp
here would fire "your client just opened it" alerts for proposals sent months
ago.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e88a9e9fa861"
down_revision: str | None = "b3f1c7d92a04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column("first_viewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "quotes",
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "quotes",
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("quotes", "view_count")
    op.drop_column("quotes", "last_viewed_at")
    op.drop_column("quotes", "first_viewed_at")
