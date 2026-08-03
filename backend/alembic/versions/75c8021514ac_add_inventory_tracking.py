"""add inventory tracking

Adds the inventory domain: where stock sits, what is tracked, every movement,
and a derived on-hand cache.

- ``inventory_locations`` — a warehouse / truck / other place stock sits. The
  service lazily creates a "Main" warehouse on first movement, so no onboarding
  step is required before receiving stock.
- ``inventory_items`` — the tracked SKU, optionally linked to a ``catalog_items``
  row (``ON DELETE SET NULL``: deleting a price-book template must never destroy
  stock history). ``reorder_point IS NULL`` means "not managed".
- ``inventory_ledger_entries`` — the append-only movement log. Rows are never
  updated or deleted; corrections are new compensating entries. The
  ``inventory_ledger_reason`` enum is created here (models declare it with
  ``create_type=False``), and the partial-unique index on job usage makes a
  retried "consume on job" request idempotent instead of double-consuming.
- ``inventory_stock_levels`` — the derived item+location cache (Bin/quant),
  rebuildable by replaying the ledger.

Purely additive: no existing table is touched.

Revision ID: 75c8021514ac
Revises: e88a9e9fa861
Create Date: 2026-08-03 17:53:11.001365

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '75c8021514ac'
down_revision: Union[str, None] = 'e88a9e9fa861'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LOCATION_KIND_VALUES = ("warehouse", "truck", "other")
LOCATION_KIND_ENUM = "inventory_location_kind"

LEDGER_REASON_VALUES = (
    "receipt",
    "job_usage",
    "sale",
    "adjustment",
    "shrinkage",
    "return_to_stock",
    "transfer_in",
    "transfer_out",
    "opening_balance",
)
LEDGER_REASON_ENUM = "inventory_ledger_reason"


def _location_kind() -> postgresql.ENUM:
    return postgresql.ENUM(*LOCATION_KIND_VALUES, name=LOCATION_KIND_ENUM, create_type=False)


def _ledger_reason() -> postgresql.ENUM:
    return postgresql.ENUM(*LEDGER_REASON_VALUES, name=LEDGER_REASON_ENUM, create_type=False)


def upgrade() -> None:
    location_kind = _location_kind()
    ledger_reason = _ledger_reason()
    location_kind.create(op.get_bind(), checkfirst=True)
    ledger_reason.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'inventory_locations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('kind', location_kind, nullable=False),
        sa.Column('crew_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['crew_id'],
            ['crews.id'],
            name=op.f('fk_inventory_locations_crew_id_crews'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            name=op.f('fk_inventory_locations_workspace_id_workspaces'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_locations')),
    )
    op.create_index(
        op.f('ix_inventory_locations_crew_id'), 'inventory_locations', ['crew_id'], unique=False
    )
    op.create_index(
        'ix_inventory_locations_workspace_active',
        'inventory_locations',
        ['workspace_id', 'is_active'],
        unique=False,
    )
    op.create_index(
        op.f('ix_inventory_locations_workspace_id'),
        'inventory_locations',
        ['workspace_id'],
        unique=False,
    )
    # Case-insensitive name uniqueness: "Main" and "main" are the same shelf.
    op.create_index(
        'uq_inventory_locations_workspace_name',
        'inventory_locations',
        ['workspace_id', sa.literal_column('lower(name)')],
        unique=True,
    )

    op.create_table(
        'inventory_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('catalog_item_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('sku', sa.String(length=100), nullable=True),
        sa.Column('unit_of_measure', sa.String(length=30), server_default='each', nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column(
            'valuation_method',
            sa.String(length=30),
            server_default='weighted_average',
            nullable=False,
        ),
        sa.Column('reorder_point', sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column('reorder_quantity', sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column(
            'safety_stock', sa.Numeric(precision=14, scale=4), server_default='0', nullable=False
        ),
        sa.Column('lead_time_days', sa.Integer(), nullable=True),
        sa.Column('supplier_name', sa.String(length=255), nullable=True),
        sa.Column('supplier_sku', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['catalog_item_id'],
            ['catalog_items.id'],
            name=op.f('fk_inventory_items_catalog_item_id_catalog_items'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['created_by_id'],
            ['users.id'],
            name=op.f('fk_inventory_items_created_by_id_users'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            name=op.f('fk_inventory_items_workspace_id_workspaces'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_items')),
    )
    op.create_index(
        op.f('ix_inventory_items_catalog_item_id'),
        'inventory_items',
        ['catalog_item_id'],
        unique=False,
    )
    op.create_index(
        'ix_inventory_items_workspace_active',
        'inventory_items',
        ['workspace_id', 'is_active'],
        unique=False,
    )
    op.create_index(
        op.f('ix_inventory_items_workspace_id'), 'inventory_items', ['workspace_id'], unique=False
    )
    op.create_index(
        'uq_inventory_items_workspace_catalog_item',
        'inventory_items',
        ['workspace_id', 'catalog_item_id'],
        unique=True,
        postgresql_where=sa.text('catalog_item_id IS NOT NULL'),
    )
    op.create_index(
        'uq_inventory_items_workspace_sku',
        'inventory_items',
        ['workspace_id', 'sku'],
        unique=True,
        postgresql_where=sa.text('sku IS NOT NULL'),
    )

    op.create_table(
        'inventory_ledger_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('location_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('quantity_delta', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('unit_cost', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('value_delta', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('reason', ledger_reason, nullable=False),
        sa.Column('reference_type', sa.String(length=20), nullable=True),
        sa.Column('reference_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('quantity_after', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('value_after', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('unit_cost_after', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['created_by_id'],
            ['users.id'],
            name=op.f('fk_inventory_ledger_entries_created_by_id_users'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['item_id'],
            ['inventory_items.id'],
            name=op.f('fk_inventory_ledger_entries_item_id_inventory_items'),
            ondelete='CASCADE',
        ),
        # RESTRICT: a location with movement history must not be deletable, or
        # the only record of where stock went disappears with it.
        sa.ForeignKeyConstraint(
            ['location_id'],
            ['inventory_locations.id'],
            name=op.f('fk_inventory_ledger_entries_location_id_inventory_locations'),
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            name=op.f('fk_inventory_ledger_entries_workspace_id_workspaces'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_ledger_entries')),
    )
    op.create_index(
        op.f('ix_inventory_ledger_entries_item_id'),
        'inventory_ledger_entries',
        ['item_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_inventory_ledger_entries_location_id'),
        'inventory_ledger_entries',
        ['location_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_inventory_ledger_entries_workspace_id'),
        'inventory_ledger_entries',
        ['workspace_id'],
        unique=False,
    )
    op.create_index(
        'ix_inventory_ledger_workspace_item',
        'inventory_ledger_entries',
        ['workspace_id', 'item_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_inventory_ledger_workspace_reason',
        'inventory_ledger_entries',
        ['workspace_id', 'reason', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_inventory_ledger_workspace_reference',
        'inventory_ledger_entries',
        ['workspace_id', 'reference_type', 'reference_id'],
        unique=False,
    )
    # Idempotency guard: one job_usage row per (job, item), so a retried
    # "consume on job" request conflicts instead of double-consuming.
    op.create_index(
        'uq_inventory_ledger_job_usage',
        'inventory_ledger_entries',
        ['workspace_id', 'reason', 'reference_type', 'reference_id', 'item_id'],
        unique=True,
        postgresql_where=sa.text("reference_id IS NOT NULL AND reason = 'job_usage'"),
    )

    op.create_table(
        'inventory_stock_levels',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('location_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            'quantity_on_hand',
            sa.Numeric(precision=14, scale=4),
            server_default='0',
            nullable=False,
        ),
        sa.Column(
            'total_value', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False
        ),
        sa.Column(
            'avg_unit_cost', sa.Numeric(precision=12, scale=4), server_default='0', nullable=False
        ),
        sa.Column('last_movement_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['item_id'],
            ['inventory_items.id'],
            name=op.f('fk_inventory_stock_levels_item_id_inventory_items'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['location_id'],
            ['inventory_locations.id'],
            name=op.f('fk_inventory_stock_levels_location_id_inventory_locations'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            name=op.f('fk_inventory_stock_levels_workspace_id_workspaces'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_stock_levels')),
        sa.UniqueConstraint(
            'workspace_id',
            'item_id',
            'location_id',
            name='uq_inventory_stock_levels_item_location',
        ),
    )
    op.create_index(
        op.f('ix_inventory_stock_levels_item_id'),
        'inventory_stock_levels',
        ['item_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_inventory_stock_levels_location_id'),
        'inventory_stock_levels',
        ['location_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_inventory_stock_levels_workspace_id'),
        'inventory_stock_levels',
        ['workspace_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_inventory_stock_levels_workspace_id'), table_name='inventory_stock_levels'
    )
    op.drop_index(
        op.f('ix_inventory_stock_levels_location_id'), table_name='inventory_stock_levels'
    )
    op.drop_index(op.f('ix_inventory_stock_levels_item_id'), table_name='inventory_stock_levels')
    op.drop_table('inventory_stock_levels')

    op.drop_index(
        'uq_inventory_ledger_job_usage',
        table_name='inventory_ledger_entries',
        postgresql_where=sa.text("reference_id IS NOT NULL AND reason = 'job_usage'"),
    )
    op.drop_index('ix_inventory_ledger_workspace_reference', table_name='inventory_ledger_entries')
    op.drop_index('ix_inventory_ledger_workspace_reason', table_name='inventory_ledger_entries')
    op.drop_index('ix_inventory_ledger_workspace_item', table_name='inventory_ledger_entries')
    op.drop_index(
        op.f('ix_inventory_ledger_entries_workspace_id'), table_name='inventory_ledger_entries'
    )
    op.drop_index(
        op.f('ix_inventory_ledger_entries_location_id'), table_name='inventory_ledger_entries'
    )
    op.drop_index(op.f('ix_inventory_ledger_entries_item_id'), table_name='inventory_ledger_entries')
    op.drop_table('inventory_ledger_entries')

    op.drop_index(
        'uq_inventory_items_workspace_sku',
        table_name='inventory_items',
        postgresql_where=sa.text('sku IS NOT NULL'),
    )
    op.drop_index(
        'uq_inventory_items_workspace_catalog_item',
        table_name='inventory_items',
        postgresql_where=sa.text('catalog_item_id IS NOT NULL'),
    )
    op.drop_index(op.f('ix_inventory_items_workspace_id'), table_name='inventory_items')
    op.drop_index('ix_inventory_items_workspace_active', table_name='inventory_items')
    op.drop_index(op.f('ix_inventory_items_catalog_item_id'), table_name='inventory_items')
    op.drop_table('inventory_items')

    op.drop_index('uq_inventory_locations_workspace_name', table_name='inventory_locations')
    op.drop_index(op.f('ix_inventory_locations_workspace_id'), table_name='inventory_locations')
    op.drop_index('ix_inventory_locations_workspace_active', table_name='inventory_locations')
    op.drop_index(op.f('ix_inventory_locations_crew_id'), table_name='inventory_locations')
    op.drop_table('inventory_locations')

    _ledger_reason().drop(op.get_bind(), checkfirst=True)
    _location_kind().drop(op.get_bind(), checkfirst=True)
