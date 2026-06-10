"""Make human_nudges.contact_id nullable for workspace-level operator nudges.

Operator-level nudges (e.g. "212 fresh advertisers ready", "7 approvals
waiting") describe the state of the workspace rather than a single contact,
so the contact FK becomes optional. Additive/nullable change only.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "human_nudges",
        "contact_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )


def downgrade() -> None:
    # Workspace-level nudges have no contact; remove them before re-tightening.
    op.execute("DELETE FROM human_nudges WHERE contact_id IS NULL")
    op.alter_column(
        "human_nudges",
        "contact_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
