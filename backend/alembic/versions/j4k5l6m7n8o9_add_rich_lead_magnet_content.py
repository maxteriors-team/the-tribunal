"""add_rich_lead_magnet_content

Revision ID: j4k5l6m7n8o9
Revises: 32440f2a725e
Create Date: 2026-01-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'j4k5l6m7n8o9'
down_revision: str | None = "32440f2a725e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add content_data JSONB column to lead_magnets for rich content
    op.add_column('lead_magnets', sa.Column('content_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # Create lead_magnet_leads table to track captured leads
    op.create_table('lead_magnet_leads',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('lead_magnet_id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone_number', sa.String(length=50), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('quiz_answers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('calculator_inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('delivered', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source_offer_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['lead_magnet_id'], ['lead_magnets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_offer_id'], ['offers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lead_magnet_leads_lead_magnet_id'), 'lead_magnet_leads', ['lead_magnet_id'], unique=False)
    op.create_index(op.f('ix_lead_magnet_leads_workspace_id'), 'lead_magnet_leads', ['workspace_id'], unique=False)
    op.create_index(op.f('ix_lead_magnet_leads_email'), 'lead_magnet_leads', ['email'], unique=False)
    op.create_index(op.f('ix_lead_magnet_leads_contact_id'), 'lead_magnet_leads', ['contact_id'], unique=False)


def downgrade() -> None:
    # Drop lead_magnet_leads table
    op.drop_index(op.f('ix_lead_magnet_leads_contact_id'), table_name='lead_magnet_leads')
    op.drop_index(op.f('ix_lead_magnet_leads_email'), table_name='lead_magnet_leads')
    op.drop_index(op.f('ix_lead_magnet_leads_workspace_id'), table_name='lead_magnet_leads')
    op.drop_index(op.f('ix_lead_magnet_leads_lead_magnet_id'), table_name='lead_magnet_leads')
    op.drop_table('lead_magnet_leads')

    # Remove content_data column from lead_magnets
    op.drop_column('lead_magnets', 'content_data')
