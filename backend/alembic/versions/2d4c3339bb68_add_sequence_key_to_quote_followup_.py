"""add sequence key to quote followup touch ledger

Revision ID: 2d4c3339bb68
Revises: 9316dc32e25b
Create Date: 2026-07-29

Two cadences now write to ``quote_followup_touches``: the first-14-days
post-estimate sequence (offsets measured from ``Quote.sent_at``) and long-range
unsold-quote revival (offsets measured from the issue date). Without a
discriminator each worker would read the other's rows as its own completed work
and silently skip touches.

Purely additive and safe on live data: the new column lands with a
``'post_estimate'`` server default, which is exactly what every pre-existing row
is, so no backfill is needed and no row is rewritten with a wrong value.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d4c3339bb68"
down_revision: str | None = "9316dc32e25b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the sequence discriminator and widen the idempotency key."""
    op.add_column(
        "quote_followup_touches",
        sa.Column(
            "sequence_key",
            sa.String(length=30),
            server_default="post_estimate",
            nullable=False,
        ),
    )
    op.drop_constraint(
        op.f("uq_quote_followup_touches_quote_offset"),
        "quote_followup_touches",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_quote_followup_touches_quote_sequence_offset",
        "quote_followup_touches",
        ["quote_id", "sequence_key", "offset_days"],
    )


def downgrade() -> None:
    """Restore the single-sequence ledger key.

    Safe to run: the schemas keep the two cadences on disjoint offset ranges
    (post-estimate 0-14, revival 15+), so no quote can hold two rows that
    collide on ``(quote_id, offset_days)`` once ``sequence_key`` is dropped.
    """
    op.drop_constraint(
        "uq_quote_followup_touches_quote_sequence_offset",
        "quote_followup_touches",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_quote_followup_touches_quote_offset"),
        "quote_followup_touches",
        ["quote_id", "offset_days"],
    )
    op.drop_column("quote_followup_touches", "sequence_key")
