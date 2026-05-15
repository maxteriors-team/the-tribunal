"""add_drip_campaigns_and_enrollments

Revision ID: db01e2f3a4b5
Revises: ca01b2c3d4e5
Create Date: 2026-04-08 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'db01e2f3a4b5'
down_revision: str | None = "ca01b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'drip_campaigns',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True),
                   sa.ForeignKey('workspaces.id', ondelete='CASCADE'),
                   nullable=False, index=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                   sa.ForeignKey('agents.id', ondelete='SET NULL'),
                   nullable=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='draft', index=True),
        sa.Column('from_phone_number', sa.String(50), nullable=False),
        sa.Column('sequence_steps', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('sending_hours_start', sa.Time(), nullable=True),
        sa.Column('sending_hours_end', sa.Time(), nullable=True),
        sa.Column('sending_days', postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column('timezone', sa.String(50), nullable=False, server_default='America/New_York'),
        sa.Column('messages_per_minute', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('total_enrolled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_completed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_responded', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_cancelled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_messages_sent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_appointments_booked', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.func.now()),
    )

    op.create_table(
        'drip_enrollments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('drip_campaign_id', postgresql.UUID(as_uuid=True),
                   sa.ForeignKey('drip_campaigns.id', ondelete='CASCADE'),
                   nullable=False, index=True),
        sa.Column('contact_id', sa.BigInteger(),
                   sa.ForeignKey('contacts.id', ondelete='CASCADE'),
                   nullable=False, index=True),
        sa.Column('status', sa.String(50), nullable=False, default='active', index=True),
        sa.Column('current_step', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_step_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column('response_category', sa.String(50), nullable=True),
        sa.Column('cancel_reason', sa.String(255), nullable=True),
        sa.Column('messages_sent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('messages_received', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_reply_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('enrolled_at', sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.func.now()),
        sa.UniqueConstraint('drip_campaign_id', 'contact_id', name='uq_drip_enrollment'),
    )

    # Composite index for the worker query: find active enrollments due for processing
    op.create_index(
        'ix_drip_enrollment_next_step',
        'drip_enrollments',
        ['status', 'next_step_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_drip_enrollment_next_step', table_name='drip_enrollments')
    op.drop_table('drip_enrollments')
    op.drop_table('drip_campaigns')
