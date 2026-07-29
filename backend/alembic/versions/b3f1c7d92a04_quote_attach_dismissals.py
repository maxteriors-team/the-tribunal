"""Record attach-prompt dismissals on quotes.

Revision ID: b3f1c7d92a04
Revises: 7dc9d61efed7
Create Date: 2026-07-29 14:05:11.203914

``quotes.primary_service`` / ``attach_count`` / ``attach_value`` (revision
``cacf6d2e5463``) report what actually rode along on a quote. They cannot say
*why* nothing did: a workspace sitting at a 20% attach rate looks exactly the
same whether the other 80% of jobs were never asked about or were asked and
declined, and those two problems have opposite fixes — coaching in the first
case, pricing or packaging in the second.

``quotes.attach_dismissals`` closes that gap. Each entry is a
``{primary_service, categories, reason, dismissed_at}`` object written by the
quote save path when a rep dismisses the attach prompt configured in
``workspace.settings["attach_rules"]``.

Purely additive and safe on live data: one NOT NULL JSONB column landing with a
``'[]'`` server default (no table rewrite, no downtime), and no backfill is
possible or meaningful — a dismissal is an event that was never captured before
this migration, so historical quotes correctly read as "nobody recorded a
dismissal" rather than as "nobody was asked".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f1c7d92a04"
down_revision: str | None = "7dc9d61efed7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column(
            "attach_dismissals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("quotes", "attach_dismissals")
