"""Add the durable technician Lighting League XP ledger.

Revision ID: 20260903_technician_scoreboard
Revises: 20260903_job_handoff_images
Create Date: 2026-09-03

Expand-only: existing quotes are ordinary, technicians start at level one, and no
historical XP rows are created.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260903_technician_scoreboard"
down_revision: str | None = "20260903_job_handoff_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add scoreboard state without rewriting or backfilling business records."""
    op.add_column(
        "quotes",
        sa.Column(
            "is_onsite_upsell",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "technicians",
        sa.Column(
            "scoreboard_level_seen",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_table(
        "technician_xp_awards",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("technician_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("source_key", sa.String(length=80), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column(
            "awarded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "category IN ('attendance', 'job', 'upsell')",
            name="ck_technician_xp_awards_category",
        ),
        sa.CheckConstraint(
            "points > 0",
            name="ck_technician_xp_awards_points_positive",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= awarded_at",
            name="ck_technician_xp_awards_revocation_order",
        ),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["technicians.id"],
            name="fk_technician_xp_awards_technician_id_technicians",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_technician_xp_awards_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_technician_xp_awards"),
        sa.UniqueConstraint(
            "workspace_id",
            "technician_id",
            "category",
            "source_key",
            name="uq_technician_xp_awards_source",
        ),
    )
    op.create_index(
        "ix_technician_xp_awards_workspace_awarded_active",
        "technician_xp_awards",
        ["workspace_id", "awarded_at"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_technician_xp_awards_workspace_technician_active",
        "technician_xp_awards",
        ["workspace_id", "technician_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    """Remove only scoreboard structures in isolated CI environments."""
    op.drop_index(
        "ix_technician_xp_awards_workspace_technician_active",
        table_name="technician_xp_awards",
    )
    op.drop_index(
        "ix_technician_xp_awards_workspace_awarded_active",
        table_name="technician_xp_awards",
    )
    op.drop_table("technician_xp_awards")
    op.drop_column("technicians", "scoreboard_level_seen")
    op.drop_column("quotes", "is_onsite_upsell")
