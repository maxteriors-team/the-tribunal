"""Add avatar_url to users and contacts.

Revision ID: cc1d2e3f4a5b
Revises: bb1c2d3e4f5a
Create Date: 2026-05-15 12:00:00.000000

Note (2026-05-20): renamed from duplicate ``a9b0c1d2e3f4`` to ``cc1d2e3f4a5b``
to resolve a triple-collision on that revision id (the original is
``a9b0c1d2e3f4_add_assistant_conversation_tables.py``). Chained after
``bb1c2d3e4f5a`` (the other ex-duplicate) so both renamed siblings run
on the merged post-feature schema. Final head of the unified graph.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cc1d2e3f4a5b"
down_revision: str | None = "bb1c2d3e4f5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contacts", "avatar_url")
    op.drop_column("users", "avatar_url")
