"""add lighting projects

Revision ID: 20260811_lighting_projects
Revises: 20260811_message_attachments
Create Date: 2026-08-11 00:00:02.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260811_lighting_projects"
down_revision: str | Sequence[str] | None = "20260811_message_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lighting_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=False),
        sa.Column("service_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name="ck_lighting_projects_status"
        ),
        sa.CheckConstraint("version > 0", name="ck_lighting_projects_version_positive"),
        sa.ForeignKeyConstraint(
            ["assigned_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["service_location_id"],
            ["service_locations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lighting_projects_workspace_id",
        "lighting_projects",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_lighting_projects_workspace_status_updated",
        "lighting_projects",
        ["workspace_id", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_lighting_projects_workspace_contact",
        "lighting_projects",
        ["workspace_id", "contact_id"],
        unique=False,
    )
    op.create_index(
        "ix_lighting_projects_workspace_opportunity",
        "lighting_projects",
        ["workspace_id", "opportunity_id"],
        unique=False,
    )
    op.create_index(
        "ix_lighting_projects_workspace_assignee",
        "lighting_projects",
        ["workspace_id", "assigned_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lighting_projects_workspace_assignee", table_name="lighting_projects"
    )
    op.drop_index(
        "ix_lighting_projects_workspace_opportunity", table_name="lighting_projects"
    )
    op.drop_index(
        "ix_lighting_projects_workspace_contact", table_name="lighting_projects"
    )
    op.drop_index(
        "ix_lighting_projects_workspace_status_updated", table_name="lighting_projects"
    )
    op.drop_index("ix_lighting_projects_workspace_id", table_name="lighting_projects")
    op.drop_table("lighting_projects")
