"""Neighbor outreach: the persisted "work the street" list for a finished job.

Revision ID: 8d7ca9999bfc
Revises: 2ed53a445f1f
Create Date: 2026-07-30 11:09:12.621995

A completed job is the moment the surrounding street is warmest — the neighbours
watched the crew work and can see the result from their own porch. Radius search
itself needs no schema (``service_locations.latitude``/``longitude`` are already
plain ``double precision``; the postal fields are Fernet-encrypted and therefore
not SQL-queryable). What needed schema is *remembering* the list, so the same
neighbour is never worked twice for the same job.

Adds:

- ``neighbor_outreach_batches`` — one list per job, unique on ``job_id`` so a
  repeated generate (an operator clicking twice, or the completion hook racing a
  manual run) tops the same batch up instead of duplicating the street. Snapshots
  ``origin_latitude``/``origin_longitude``/``radius_meters`` so the list stays
  explainable after the site is re-geocoded or the workspace setting changes.
- ``neighbor_outreach_entries`` — one neighbour per batch, unique on
  ``(batch_id, service_location_id)``: the constraint that makes "never worked
  twice" a database guarantee rather than a convention. ``status`` and ``channel``
  are ``VARCHAR(50)`` (``native_enum=False``), not Postgres ``ENUM`` types, so a
  future status/channel needs no ``ALTER TYPE`` — same treatment as
  ``referral_partners.partner_type``.

No address is copied onto an entry: postal fields stay encrypted on
``service_locations`` and the export joins through, rather than duplicating
customer PII into a second table.

``channel`` defaults to ``print`` (door hanger / direct mail) because a radius
returns addresses, not permission — messaging is reserved for neighbours who map
to a consented contact, and ``messaging_blocked_reason`` persists why an entry
stayed print-only.

Reversible and non-destructive on upgrade: both tables are new and start empty.
The downgrade drops outreach history that cannot be reconstructed (the per-entry
worked/skipped/converted statuses an operator set by hand).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d7ca9999bfc"
down_revision: str | None = "2ed53a445f1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = sa.Enum(
    "pending",
    "contacted",
    "skipped",
    "converted",
    name="neighboroutreachstatus",
    native_enum=False,
    create_constraint=False,
    length=50,
)

_CHANNEL = sa.Enum(
    "print",
    "sms",
    "email",
    name="neighboroutreachchannel",
    native_enum=False,
    create_constraint=False,
    length=50,
)


def upgrade() -> None:
    op.create_table(
        "neighbor_outreach_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("origin_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Snapshot of the search, so the list stays explainable later.
        sa.Column("origin_latitude", sa.Float(), nullable=False),
        sa.Column("origin_longitude", sa.Float(), nullable=False),
        sa.Column("radius_meters", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Deleting the job deletes the list it produced (meaningless without it);
        # deleting the origin site only nulls the pointer, since the snapshot
        # coordinates above keep the batch usable.
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["field_service_jobs.id"],
            name=op.f("fk_neighbor_outreach_batches_job_id_field_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["origin_location_id"],
            ["service_locations.id"],
            name=op.f("fk_neighbor_outreach_batches_origin_location_id_service_locations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_neighbor_outreach_batches_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_neighbor_outreach_batches")),
        # One batch per job: the idempotency guard for repeated generation.
        sa.UniqueConstraint("job_id", name="uq_neighbor_outreach_batches_job"),
    )
    op.create_index(
        op.f("ix_neighbor_outreach_batches_job_id"),
        "neighbor_outreach_batches",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_neighbor_outreach_batches_origin_location_id"),
        "neighbor_outreach_batches",
        ["origin_location_id"],
        unique=False,
    )
    op.create_index(
        "ix_neighbor_outreach_batches_workspace_created",
        "neighbor_outreach_batches",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_neighbor_outreach_batches_workspace_id"),
        "neighbor_outreach_batches",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "neighbor_outreach_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # Denormalized tenant column so reads scope through app.db.scope without
        # joining back to the batch.
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_location_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Nullable: an address-only canvass row has no customer behind it, and a
        # null here is exactly what forces the print channel.
        sa.Column("contact_id", sa.BigInteger(), nullable=True),
        sa.Column("distance_meters", sa.Float(), nullable=False),
        sa.Column("status", _STATUS, server_default="pending", nullable=False),
        sa.Column("channel", _CHANNEL, server_default="print", nullable=False),
        # Why this entry is print-only ("no_contact", "missing_sms_consent",
        # "global_opt_out", ...). Null when messaging is allowed.
        sa.Column("messaging_blocked_reason", sa.String(length=50), nullable=True),
        sa.Column("contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["neighbor_outreach_batches.id"],
            name=op.f("fk_neighbor_outreach_entries_batch_id_neighbor_outreach_batches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_neighbor_outreach_entries_contact_id_contacts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["service_location_id"],
            ["service_locations.id"],
            name=op.f("fk_neighbor_outreach_entries_service_location_id_service_locations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_neighbor_outreach_entries_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_neighbor_outreach_entries")),
        # The core promise: one row per neighbour per job.
        sa.UniqueConstraint(
            "batch_id",
            "service_location_id",
            name="uq_neighbor_outreach_entries_batch_location",
        ),
    )
    op.create_index(
        "ix_neighbor_outreach_entries_batch_distance",
        "neighbor_outreach_entries",
        ["batch_id", "distance_meters"],
        unique=False,
    )
    op.create_index(
        op.f("ix_neighbor_outreach_entries_batch_id"),
        "neighbor_outreach_entries",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_neighbor_outreach_entries_contact_id"),
        "neighbor_outreach_entries",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_neighbor_outreach_entries_service_location_id"),
        "neighbor_outreach_entries",
        ["service_location_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_neighbor_outreach_entries_workspace_id"),
        "neighbor_outreach_entries",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_neighbor_outreach_entries_workspace_status",
        "neighbor_outreach_entries",
        ["workspace_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_neighbor_outreach_entries_workspace_status",
        table_name="neighbor_outreach_entries",
    )
    op.drop_index(
        op.f("ix_neighbor_outreach_entries_workspace_id"),
        table_name="neighbor_outreach_entries",
    )
    op.drop_index(
        op.f("ix_neighbor_outreach_entries_service_location_id"),
        table_name="neighbor_outreach_entries",
    )
    op.drop_index(
        op.f("ix_neighbor_outreach_entries_contact_id"),
        table_name="neighbor_outreach_entries",
    )
    op.drop_index(
        op.f("ix_neighbor_outreach_entries_batch_id"),
        table_name="neighbor_outreach_entries",
    )
    op.drop_index(
        "ix_neighbor_outreach_entries_batch_distance",
        table_name="neighbor_outreach_entries",
    )
    op.drop_table("neighbor_outreach_entries")

    op.drop_index(
        op.f("ix_neighbor_outreach_batches_workspace_id"),
        table_name="neighbor_outreach_batches",
    )
    op.drop_index(
        "ix_neighbor_outreach_batches_workspace_created",
        table_name="neighbor_outreach_batches",
    )
    op.drop_index(
        op.f("ix_neighbor_outreach_batches_origin_location_id"),
        table_name="neighbor_outreach_batches",
    )
    op.drop_index(
        op.f("ix_neighbor_outreach_batches_job_id"),
        table_name="neighbor_outreach_batches",
    )
    op.drop_table("neighbor_outreach_batches")
