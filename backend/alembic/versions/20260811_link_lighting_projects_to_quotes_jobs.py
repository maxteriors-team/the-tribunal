"""link lighting projects to accepted quotes and field-service jobs

Revision ID: 20260811_lighting_handoff
Revises: 20260811_lighting_projects
Create Date: 2026-08-12 00:00:00.000000

The links are additive and nullable so existing quotes, jobs, and lighting projects
remain valid.  Downgrade removes only this linkage metadata; it never deletes a
customer record or design document.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260811_lighting_handoff"
down_revision: str | Sequence[str] | None = "20260811_lighting_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lighting_projects",
        sa.Column("installation_shot_id", sa.String(length=250), nullable=True),
    )

    op.add_column(
        "quotes",
        sa.Column(
            "lighting_project_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_quotes_lighting_project_id_lighting_projects",
        "quotes",
        "lighting_projects",
        ["lighting_project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_quotes_workspace_lighting_project",
        "quotes",
        ["workspace_id", "lighting_project_id"],
        unique=False,
    )

    op.add_column(
        "field_service_jobs",
        sa.Column("source_quote_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "field_service_jobs",
        sa.Column(
            "lighting_project_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_field_service_jobs_source_quote_id_quotes",
        "field_service_jobs",
        "quotes",
        ["source_quote_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_field_service_jobs_lighting_project_id_lighting_projects",
        "field_service_jobs",
        "lighting_projects",
        ["lighting_project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_field_service_jobs_source_quote",
        "field_service_jobs",
        ["source_quote_id"],
    )
    op.create_index(
        "ix_field_service_jobs_workspace_lighting_project",
        "field_service_jobs",
        ["workspace_id", "lighting_project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_field_service_jobs_workspace_lighting_project",
        table_name="field_service_jobs",
    )
    op.drop_constraint(
        "uq_field_service_jobs_source_quote",
        "field_service_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "fk_field_service_jobs_lighting_project_id_lighting_projects",
        "field_service_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_field_service_jobs_source_quote_id_quotes",
        "field_service_jobs",
        type_="foreignkey",
    )
    op.drop_column("field_service_jobs", "lighting_project_id")
    op.drop_column("field_service_jobs", "source_quote_id")

    op.drop_index("ix_quotes_workspace_lighting_project", table_name="quotes")
    op.drop_constraint(
        "fk_quotes_lighting_project_id_lighting_projects",
        "quotes",
        type_="foreignkey",
    )
    op.drop_column("quotes", "lighting_project_id")

    op.drop_column("lighting_projects", "installation_shot_id")
