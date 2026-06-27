"""add field-service jobs and assignments

Adds the dispatch layer on top of crews/technicians/service-locations:

- ``field_service_jobs`` \u2014 a unit of field work (work order) for a customer at a
  service location, with an optional crew lane and a nullable time window. The
  ``field_service_job_status`` Postgres enum tracks its lifecycle. ``external_*``
  columns + a partial-unique index leave room for an idempotent Jobber job sync.
- ``field_service_job_assignments`` \u2014 the many-to-many tag between a job and a
  technician (a job can have several technicians; tagging the same one twice is a
  no-op via the unique constraint). Each assigned worker sees the job on their
  calendar.

Revision ID: c4f9e2b1a7d8
Revises: b3d8f1a2c4e5
Create Date: 2026-06-26 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c4f9e2b1a7d8"
down_revision: Union[str, None] = "b3d8f1a2c4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


JOB_STATUS_VALUES = ("unscheduled", "scheduled", "in_progress", "completed", "cancelled")
JOB_STATUS_ENUM = "field_service_job_status"


def upgrade() -> None:
    job_status = postgresql.ENUM(
        *JOB_STATUS_VALUES,
        name=JOB_STATUS_ENUM,
        create_type=False,
    )
    job_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "field_service_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=False),
        sa.Column("service_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", job_status, nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_source", sa.String(length=50), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_field_service_jobs_contact_id_contacts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["crew_id"],
            ["crews.id"],
            name=op.f("fk_field_service_jobs_crew_id_crews"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["service_location_id"],
            ["service_locations.id"],
            name=op.f("fk_field_service_jobs_service_location_id_service_locations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_field_service_jobs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_service_jobs")),
    )
    op.create_index(
        op.f("ix_field_service_jobs_contact_id"),
        "field_service_jobs",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_field_service_jobs_crew_id"),
        "field_service_jobs",
        ["crew_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_field_service_jobs_service_location_id"),
        "field_service_jobs",
        ["service_location_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_field_service_jobs_workspace_id"),
        "field_service_jobs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_field_service_jobs_workspace_status",
        "field_service_jobs",
        ["workspace_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_field_service_jobs_workspace_scheduled_start",
        "field_service_jobs",
        ["workspace_id", "scheduled_start"],
        unique=False,
    )
    op.create_index(
        "ix_field_service_jobs_workspace_crew",
        "field_service_jobs",
        ["workspace_id", "crew_id"],
        unique=False,
    )
    op.create_index(
        "uq_field_service_jobs_workspace_external",
        "field_service_jobs",
        ["workspace_id", "external_source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.create_table(
        "field_service_job_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("technician_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["field_service_jobs.id"],
            name=op.f("fk_field_service_job_assignments_job_id_field_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["technicians.id"],
            name=op.f("fk_field_service_job_assignments_technician_id_technicians"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_service_job_assignments")),
        sa.UniqueConstraint(
            "job_id",
            "technician_id",
            name="uq_field_service_job_assignments_job_tech",
        ),
    )
    op.create_index(
        op.f("ix_field_service_job_assignments_job_id"),
        "field_service_job_assignments",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_field_service_job_assignments_technician",
        "field_service_job_assignments",
        ["technician_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_field_service_job_assignments_technician",
        table_name="field_service_job_assignments",
    )
    op.drop_index(
        op.f("ix_field_service_job_assignments_job_id"),
        table_name="field_service_job_assignments",
    )
    op.drop_table("field_service_job_assignments")

    op.drop_index(
        "uq_field_service_jobs_workspace_external",
        table_name="field_service_jobs",
    )
    op.drop_index("ix_field_service_jobs_workspace_crew", table_name="field_service_jobs")
    op.drop_index(
        "ix_field_service_jobs_workspace_scheduled_start",
        table_name="field_service_jobs",
    )
    op.drop_index("ix_field_service_jobs_workspace_status", table_name="field_service_jobs")
    op.drop_index(op.f("ix_field_service_jobs_workspace_id"), table_name="field_service_jobs")
    op.drop_index(
        op.f("ix_field_service_jobs_service_location_id"),
        table_name="field_service_jobs",
    )
    op.drop_index(op.f("ix_field_service_jobs_crew_id"), table_name="field_service_jobs")
    op.drop_index(op.f("ix_field_service_jobs_contact_id"), table_name="field_service_jobs")
    op.drop_table("field_service_jobs")

    job_status = postgresql.ENUM(
        *JOB_STATUS_VALUES,
        name=JOB_STATUS_ENUM,
        create_type=False,
    )
    job_status.drop(op.get_bind(), checkfirst=True)
