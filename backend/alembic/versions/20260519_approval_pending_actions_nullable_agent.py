"""allow assistant pending actions without agent

Revision ID: 20260519_approval_pending_actions_nullable_agent
Revises: c9e1a2b3d4f5
Create Date: 2026-05-19 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260519_approval_pending_actions_nullable_agent"
down_revision: str | Sequence[str] | None = "c9e1a2b3d4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Naming convention from app.db.base: fk_<table>_<column>_<referred_table>.
_FK_NAME = "fk_pending_actions_agent_id_agents"


def upgrade() -> None:
    op.drop_constraint(_FK_NAME, "pending_actions", type_="foreignkey")
    op.alter_column("pending_actions", "agent_id", nullable=True)
    op.create_foreign_key(
        _FK_NAME,
        "pending_actions",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, "pending_actions", type_="foreignkey")
    op.alter_column("pending_actions", "agent_id", nullable=False)
    op.create_foreign_key(
        _FK_NAME,
        "pending_actions",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )
