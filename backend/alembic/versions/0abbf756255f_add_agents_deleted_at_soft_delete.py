"""add agents.deleted_at soft delete

Revision ID: 0abbf756255f
Revises: db8b02d940fc
Create Date: 2026-08-31 16:26:36.090682

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0abbf756255f"
down_revision: Union[str, None] = "db8b02d940fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive and reversible: nullable column (no table rewrite, no backfill --
    # every existing agent stays live) plus a plain index. `agents` is a tiny
    # per-workspace table, so the non-concurrent CREATE INDEX lock is negligible.
    op.add_column("agents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_agents_deleted_at"), "agents", ["deleted_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agents_deleted_at"), table_name="agents")
    op.drop_column("agents", "deleted_at")
