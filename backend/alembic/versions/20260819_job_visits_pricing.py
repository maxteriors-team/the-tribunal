"""add job visits and priced scope

Revision ID: 20260819_job_visits_pricing
Revises: 20260818_password_reset_tokens
Create Date: 2026-08-19 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260819_job_visits_pricing"
down_revision: str | Sequence[str] | None = "20260818_password_reset_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "field_service_jobs",
        sa.Column(
            "tax_rate", sa.Numeric(precision=5, scale=2), server_default="0.00", nullable=False
        ),
    )
    op.create_table(
        "field_service_job_visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anytime", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="scheduled", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["field_service_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_field_service_job_visits_job_id", "field_service_job_visits", ["job_id"])
    op.create_index(
        "ix_field_service_job_visits_job_start",
        "field_service_job_visits",
        ["job_id", "starts_at"],
    )
    op.execute(
        """
        INSERT INTO field_service_job_visits (
            id, job_id, starts_at, ends_at, anytime, instructions, status, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), id, scheduled_start, scheduled_end, false, description,
            CASE
                WHEN status::text IN ('completed', 'cancelled', 'in_progress') THEN status::text
                ELSE 'scheduled'
            END,
            created_at, updated_at
        FROM field_service_jobs
        WHERE scheduled_start IS NOT NULL AND scheduled_end IS NOT NULL
        """
    )
    op.create_table(
        "field_service_job_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("taxable", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["field_service_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_field_service_job_line_items_job_id", "field_service_job_line_items", ["job_id"]
    )
    op.create_index(
        "ix_field_service_job_line_items_job_position",
        "field_service_job_line_items",
        ["job_id", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_field_service_job_line_items_job_position",
        table_name="field_service_job_line_items",
    )
    op.drop_index(
        "ix_field_service_job_line_items_job_id", table_name="field_service_job_line_items"
    )
    op.drop_table("field_service_job_line_items")
    op.drop_index("ix_field_service_job_visits_job_start", table_name="field_service_job_visits")
    op.drop_index("ix_field_service_job_visits_job_id", table_name="field_service_job_visits")
    op.drop_table("field_service_job_visits")
    op.drop_column("field_service_jobs", "tax_rate")
