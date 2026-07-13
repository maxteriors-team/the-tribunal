"""Add per-user new-lead notification preference column.

Adds a per-type opt-out toggle for new-lead notifications captured through
public lead-form submissions. Gates both push and email delivery for the
``new_lead`` ``notification_type``.

Revision ID: f2a3b4c5d6e8
Revises: e1f2a3b4c5d7
Create Date: 2026-07-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e8"
down_revision: str | None = "e1f2a3b4c5d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "notification_push_new_lead",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notification_push_new_lead")
