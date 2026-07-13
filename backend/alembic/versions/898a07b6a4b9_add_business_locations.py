"""add business_locations

Creates the ``business_locations`` table — a workspace's physical branches /
business units (ServiceTitan-style). Pure addition: no existing table is
touched, so this is safe to ship alone. Address fields are business data (not
customer PII), so unlike ``service_locations`` they are plain text.

Revision ID: 898a07b6a4b9
Revises: f2a3b4c5d6e8
Create Date: 2026-07-13 19:46:29.196310

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '898a07b6a4b9'
down_revision: Union[str, None] = 'f3ea78939e14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('business_locations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('timezone', sa.String(length=64), server_default='UTC', nullable=False),
    sa.Column('business_hours', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('address_line1', sa.String(length=500), nullable=True),
    sa.Column('address_line2', sa.String(length=500), nullable=True),
    sa.Column('city', sa.String(length=200), nullable=True),
    sa.Column('state', sa.String(length=200), nullable=True),
    sa.Column('postal_code', sa.String(length=50), nullable=True),
    sa.Column('country', sa.String(length=2), server_default='US', nullable=False),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_business_locations_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_business_locations')),
    sa.UniqueConstraint('workspace_id', 'name', name='uq_business_locations_workspace_name')
    )
    op.create_index('ix_business_locations_workspace_active', 'business_locations', ['workspace_id', 'is_active'], unique=False)
    op.create_index(op.f('ix_business_locations_workspace_id'), 'business_locations', ['workspace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_business_locations_workspace_id'), table_name='business_locations')
    op.drop_index('ix_business_locations_workspace_active', table_name='business_locations')
    op.drop_table('business_locations')
