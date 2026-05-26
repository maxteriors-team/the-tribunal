"""allow assistant pending actions without agent

Revision ID: 20260519_approval_pending_actions_nullable_agent
Revises: c9e1a2b3d4f5
Create Date: 2026-05-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260519_approval_pending_actions_nullable_agent"
down_revision: str | Sequence[str] | None = "c9e1a2b3d4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Naming convention from app.db.base: fk_<table>_<column>_<referred_table>.
_FK_NAME = "fk_pending_actions_agent_id_agents"


def _existing_agent_fk_name() -> str | None:
    result = op.get_bind().execute(
        sa.text(
            """
            SELECT con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            JOIN pg_attribute att
              ON att.attrelid = rel.oid
             AND att.attnum = ANY (con.conkey)
            JOIN pg_class ref_rel ON ref_rel.oid = con.confrelid
            WHERE con.contype = 'f'
              AND nsp.nspname = current_schema()
              AND rel.relname = 'pending_actions'
              AND att.attname = 'agent_id'
              AND ref_rel.relname = 'agents'
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    return str(result) if result is not None else None


def _drop_existing_agent_fk() -> None:
    existing_fk_name = _existing_agent_fk_name()
    if existing_fk_name is not None:
        op.drop_constraint(existing_fk_name, "pending_actions", type_="foreignkey")


def _create_agent_fk(*, ondelete: str) -> None:
    op.create_foreign_key(
        _FK_NAME,
        "pending_actions",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    _drop_existing_agent_fk()
    op.alter_column("pending_actions", "agent_id", nullable=True)
    _create_agent_fk(ondelete="SET NULL")


def downgrade() -> None:
    _drop_existing_agent_fk()
    op.alter_column("pending_actions", "agent_id", nullable=False)
    _create_agent_fk(ondelete="CASCADE")
