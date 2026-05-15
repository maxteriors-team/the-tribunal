"""add workspace invitations

Revision ID: 32440f2a725e
Revises: i3j4k5l6m7n8
Create Date: 2026-01-13 13:49:23.117800

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32440f2a725e'
down_revision: str | None = "i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create workspace_invitations table."""
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("invited_by_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspace_invitations_email"),
        "workspace_invitations",
        ["email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_invitations_token"),
        "workspace_invitations",
        ["token"],
        unique=True,
    )
    op.create_index(
        op.f("ix_workspace_invitations_workspace_id"),
        "workspace_invitations",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop workspace_invitations table."""
    op.drop_index(
        op.f("ix_workspace_invitations_workspace_id"), table_name="workspace_invitations"
    )
    op.drop_index(
        op.f("ix_workspace_invitations_token"), table_name="workspace_invitations"
    )
    op.drop_index(
        op.f("ix_workspace_invitations_email"), table_name="workspace_invitations"
    )
    op.drop_table("workspace_invitations")
