"""add business_location_id to jobs and appointments

Stamps field-service jobs and appointments with a business location (branch) so
the schedule/calendar/dashboard can filter and roll up by branch. Both FKs are
nullable and ``ON DELETE SET NULL`` — existing rows stay "unassigned / all
locations" and deleting a branch unassigns rather than deleting. Additive.

Revision ID: 01126145aada
Revises: fa5870a57452
Create Date: 2026-07-13 20:12:30.037715

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '01126145aada'
down_revision: Union[str, None] = 'fa5870a57452'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('appointments', sa.Column('business_location_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_appointments_business_location_id'), 'appointments', ['business_location_id'], unique=False)
    op.create_index('ix_appointments_workspace_business_location', 'appointments', ['workspace_id', 'business_location_id'], unique=False)
    op.create_foreign_key(op.f('fk_appointments_business_location_id_business_locations'), 'appointments', 'business_locations', ['business_location_id'], ['id'], ondelete='SET NULL')
    op.add_column('field_service_jobs', sa.Column('business_location_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_field_service_jobs_business_location_id'), 'field_service_jobs', ['business_location_id'], unique=False)
    op.create_index('ix_field_service_jobs_workspace_business_location', 'field_service_jobs', ['workspace_id', 'business_location_id'], unique=False)
    op.create_foreign_key(op.f('fk_field_service_jobs_business_location_id_business_locations'), 'field_service_jobs', 'business_locations', ['business_location_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_field_service_jobs_business_location_id_business_locations'), 'field_service_jobs', type_='foreignkey')
    op.drop_index('ix_field_service_jobs_workspace_business_location', table_name='field_service_jobs')
    op.drop_index(op.f('ix_field_service_jobs_business_location_id'), table_name='field_service_jobs')
    op.drop_column('field_service_jobs', 'business_location_id')
    op.drop_constraint(op.f('fk_appointments_business_location_id_business_locations'), 'appointments', type_='foreignkey')
    op.drop_index('ix_appointments_workspace_business_location', table_name='appointments')
    op.drop_index(op.f('ix_appointments_business_location_id'), table_name='appointments')
    op.drop_column('appointments', 'business_location_id')
