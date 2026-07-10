"""Add Google Calendar provider support: connections, provider columns, schedules.

Additive and fully reversible. Introduces:
- ``calendar_connections`` — per-workspace Google OAuth tokens (encrypted) plus
  watch-channel / sync-token operational state.
- ``appointments.calendar_provider`` (default ``calcom``) + ``external_event_id``
  (indexed) — provider-neutral booking identity alongside the legacy ``calcom_*``.
- ``agents.schedule_config`` / ``bookable_staff.schedule_config`` — weekly-hours
  JSON feeding the Google availability engine.

No existing Cal.com columns are renamed or dropped; live prod data is untouched.

Revision ID: c1cb7455d5cc
Revises: e1f2a3b4c5d7
Create Date: 2026-07-07 16:34:44.351991

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c1cb7455d5cc'
down_revision: Union[str, None] = 'e1f2a3b4c5d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('calendar_connections',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=50), server_default='google', nullable=False),
    sa.Column('credentials', sa.Text(), nullable=False),
    sa.Column('google_calendar_id', sa.String(length=255), nullable=True),
    sa.Column('token_expiry', sa.DateTime(timezone=True), nullable=True),
    sa.Column('scopes', sa.Text(), nullable=True),
    sa.Column('watch_channel_id', sa.String(length=255), nullable=True),
    sa.Column('watch_resource_id', sa.String(length=255), nullable=True),
    sa.Column('watch_expiration', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sync_token', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_calendar_connections_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_calendar_connections')),
    sa.UniqueConstraint('workspace_id', 'provider', name='uq_calendar_connection_workspace_provider')
    )
    op.create_index(op.f('ix_calendar_connections_workspace_id'), 'calendar_connections', ['workspace_id'], unique=False)
    op.add_column('agents', sa.Column('schedule_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('appointments', sa.Column('calendar_provider', sa.String(length=50), server_default='calcom', nullable=False))
    op.add_column('appointments', sa.Column('external_event_id', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_appointments_external_event_id'), 'appointments', ['external_event_id'], unique=False)
    op.add_column('bookable_staff', sa.Column('schedule_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('bookable_staff', 'schedule_config')
    op.drop_index(op.f('ix_appointments_external_event_id'), table_name='appointments')
    op.drop_column('appointments', 'external_event_id')
    op.drop_column('appointments', 'calendar_provider')
    op.drop_column('agents', 'schedule_config')
    op.drop_index(op.f('ix_calendar_connections_workspace_id'), table_name='calendar_connections')
    op.drop_table('calendar_connections')
