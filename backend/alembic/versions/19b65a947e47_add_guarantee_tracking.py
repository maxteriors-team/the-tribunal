"""Add guarantee tracking.

Revision ID: 19b65a947e47
Revises: f6g7h8i9j0k1
Create Date: 2026-02-14
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "19b65a947e47"
down_revision: str | None = "f6g7h8i9j0k1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add guarantee tracking columns to campaigns
    op.add_column(
        "campaigns",
        sa.Column("guarantee_target", sa.Integer(), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("guarantee_window_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("guarantee_status", sa.String(50), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("appointments_completed", sa.Integer(), server_default="0", nullable=False),
    )

    # Add campaign_id to appointments
    op.add_column(
        "appointments",
        sa.Column("campaign_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_appointments_campaign_id", "appointments", ["campaign_id"]
    )
    op.create_foreign_key(
        "fk_appointments_campaign_id",
        "appointments",
        "campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_appointments_campaign_id", "appointments", type_="foreignkey")
    op.drop_index("ix_appointments_campaign_id", table_name="appointments")
    op.drop_column("appointments", "campaign_id")
    op.drop_column("campaigns", "appointments_completed")
    op.drop_column("campaigns", "guarantee_status")
    op.drop_column("campaigns", "guarantee_window_days")
    op.drop_column("campaigns", "guarantee_target")
