"""add technician business_location_id

Tags technicians to a business location (branch). The FK is nullable and
``ON DELETE SET NULL`` — existing technicians stay "unassigned / all locations"
until an admin sets a branch, and deleting a branch unassigns its staff rather
than deleting them. Additive: no existing row or behavior changes.

Revision ID: fa5870a57452
Revises: 898a07b6a4b9
Create Date: 2026-07-13 20:07:19.600338

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa5870a57452'
down_revision: Union[str, None] = '898a07b6a4b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('technicians', sa.Column('business_location_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_technicians_business_location_id'), 'technicians', ['business_location_id'], unique=False)
    op.create_index('ix_technicians_workspace_business_location', 'technicians', ['workspace_id', 'business_location_id'], unique=False)
    op.create_foreign_key(op.f('fk_technicians_business_location_id_business_locations'), 'technicians', 'business_locations', ['business_location_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_technicians_business_location_id_business_locations'), 'technicians', type_='foreignkey')
    op.drop_index('ix_technicians_workspace_business_location', table_name='technicians')
    op.drop_index(op.f('ix_technicians_business_location_id'), table_name='technicians')
    op.drop_column('technicians', 'business_location_id')
