"""Add seasonal quote snapshots and quote-created job phases.

Revision ID: 20260909_seasonal_handoff
Revises: 20260909_conv_arbiters
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260909_seasonal_handoff"
down_revision: str | Sequence[str] | None = "20260909_conv_arbiters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '60s'")
    op.add_column(
        "quotes",
        sa.Column("seasonal_installation_snapshot", postgresql.JSONB(), nullable=True),
    )
    op.add_column("quotes", sa.Column("seasonal_takedown_included", sa.Boolean(), nullable=True))
    op.add_column("quotes", sa.Column("seasonal_storage_included", sa.Boolean(), nullable=True))

    # The server default backfills existing rows without rewriting the table on
    # supported PostgreSQL versions and keeps older application code compatible.
    op.add_column(
        "field_service_jobs",
        sa.Column(
            "source_quote_phase",
            sa.String(length=20),
            nullable=False,
            server_default="primary",
        ),
    )
    op.create_check_constraint(
        "ck_field_service_jobs_source_quote_phase",
        "field_service_jobs",
        "source_quote_phase IN ('primary', 'installation', 'takedown')",
    )
    # Build the replacement guard before removing the old one, so no migration
    # state permits duplicate jobs for the same quote and phase.
    op.create_unique_constraint(
        "uq_field_service_jobs_source_quote_phase",
        "field_service_jobs",
        ["source_quote_id", "source_quote_phase"],
    )
    op.drop_constraint(
        "uq_field_service_jobs_source_quote",
        "field_service_jobs",
        type_="unique",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '60s'")
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE field_service_jobs IN SHARE ROW EXCLUSIVE MODE"))
    duplicate_quote_id = bind.execute(
        sa.text(
            """
            SELECT source_quote_id
            FROM field_service_jobs
            WHERE source_quote_id IS NOT NULL
            GROUP BY source_quote_id
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if duplicate_quote_id is not None:
        raise RuntimeError("Refusing downgrade: at least one quote has multiple field-service jobs")

    op.create_unique_constraint(
        "uq_field_service_jobs_source_quote",
        "field_service_jobs",
        ["source_quote_id"],
    )
    op.drop_constraint(
        "uq_field_service_jobs_source_quote_phase",
        "field_service_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "ck_field_service_jobs_source_quote_phase",
        "field_service_jobs",
        type_="check",
    )
    op.drop_column("field_service_jobs", "source_quote_phase")

    op.drop_column("quotes", "seasonal_storage_included")
    op.drop_column("quotes", "seasonal_takedown_included")
    op.drop_column("quotes", "seasonal_installation_snapshot")
