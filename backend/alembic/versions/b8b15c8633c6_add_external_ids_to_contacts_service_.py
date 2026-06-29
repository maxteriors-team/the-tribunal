"""add external ids to contacts service_locations invoices

Adds nullable ``external_source`` + ``external_id`` columns to ``contacts``,
``service_locations`` and ``invoices`` so records pulled in by the one-time
Jobber import carry a stable provenance key. A partial unique index on
``(workspace_id, external_source, external_id)`` per table makes the import
idempotent: re-running upserts the same rows instead of duplicating. Natively
created records leave both columns null and are excluded by the
``external_id IS NOT NULL`` predicate. Mirrors the pattern already on
``crews`` / ``technicians`` / ``field_service_jobs``.

Revision ID: b8b15c8633c6
Revises: 4bf62e766596
Create Date: 2026-06-29 13:22:49.569677

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8b15c8633c6'
down_revision: Union[str, None] = '4bf62e766596'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('external_source', sa.String(length=50), nullable=True))
    op.add_column('contacts', sa.Column('external_id', sa.String(length=255), nullable=True))
    op.create_index('uq_contacts_workspace_external', 'contacts', ['workspace_id', 'external_source', 'external_id'], unique=True, postgresql_where=sa.text('external_id IS NOT NULL'))
    op.add_column('invoices', sa.Column('external_source', sa.String(length=50), nullable=True))
    op.add_column('invoices', sa.Column('external_id', sa.String(length=255), nullable=True))
    op.create_index('uq_invoices_workspace_external', 'invoices', ['workspace_id', 'external_source', 'external_id'], unique=True, postgresql_where=sa.text('external_id IS NOT NULL'))
    op.add_column('service_locations', sa.Column('external_source', sa.String(length=50), nullable=True))
    op.add_column('service_locations', sa.Column('external_id', sa.String(length=255), nullable=True))
    op.create_index('uq_service_locations_workspace_external', 'service_locations', ['workspace_id', 'external_source', 'external_id'], unique=True, postgresql_where=sa.text('external_id IS NOT NULL'))


def downgrade() -> None:
    op.drop_index('uq_service_locations_workspace_external', table_name='service_locations', postgresql_where=sa.text('external_id IS NOT NULL'))
    op.drop_column('service_locations', 'external_id')
    op.drop_column('service_locations', 'external_source')
    op.drop_index('uq_invoices_workspace_external', table_name='invoices', postgresql_where=sa.text('external_id IS NOT NULL'))
    op.drop_column('invoices', 'external_id')
    op.drop_column('invoices', 'external_source')
    op.drop_index('uq_contacts_workspace_external', table_name='contacts', postgresql_where=sa.text('external_id IS NOT NULL'))
    op.drop_column('contacts', 'external_id')
    op.drop_column('contacts', 'external_source')
