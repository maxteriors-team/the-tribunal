"""Add Bistro inventory job allocations.

Revision ID: 20260826_bistro_allocs
Revises: 20260822_roofline_repair
Create Date: 2026-08-26

Purely additive: existing inventory and job rows are unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_bistro_allocs"
down_revision: str | None = "20260822_roofline_repair"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_job_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "consumption_ledger_entry_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("behavior", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="reserved",
            nullable=False,
        ),
        sa.Column("planned_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("actual_quantity", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actual_quantity IS NULL OR actual_quantity >= 0",
            name="ck_inventory_job_allocations_actual_nonnegative",
        ),
        sa.CheckConstraint(
            "behavior IN ('consumable', 'reusable')",
            name="ck_inventory_job_allocations_behavior",
        ),
        sa.CheckConstraint(
            "planned_quantity > 0",
            name="ck_inventory_job_allocations_planned_positive",
        ),
        sa.CheckConstraint(
            "status IN ('reserved', 'consumed', 'deployed', 'released', 'returned')",
            name="ck_inventory_job_allocations_status",
        ),
        sa.ForeignKeyConstraint(
            ["consumption_ledger_entry_id"],
            ["inventory_ledger_entries.id"],
            name=op.f(
                "fk_inventory_job_allocations_consumption_ledger_entry_id_inventory_ledger_entries"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["inventory_items.id"],
            name=op.f("fk_inventory_job_allocations_item_id_inventory_items"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["field_service_jobs.id"],
            name=op.f("fk_inventory_job_allocations_job_id_field_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_location_id"],
            ["inventory_locations.id"],
            name=op.f("fk_inventory_job_allocations_source_location_id_inventory_locations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_inventory_job_allocations_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_job_allocations")),
        sa.UniqueConstraint(
            "consumption_ledger_entry_id",
            name=op.f("uq_inventory_job_allocations_consumption_ledger_entry_id"),
        ),
        sa.UniqueConstraint(
            "job_id",
            "item_id",
            name="uq_inventory_job_allocations_job_item",
        ),
    )
    op.create_index(
        op.f("ix_inventory_job_allocations_item_id"),
        "inventory_job_allocations",
        ["item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_job_allocations_job_id"),
        "inventory_job_allocations",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_job_allocations_source_location_id"),
        "inventory_job_allocations",
        ["source_location_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_job_allocations_workspace_id"),
        "inventory_job_allocations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_job_allocations_workspace_item_status",
        "inventory_job_allocations",
        ["workspace_id", "item_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_job_allocations_workspace_status",
        "inventory_job_allocations",
        ["workspace_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("inventory_job_allocations")
