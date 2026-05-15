"""add_offer_builder_and_lead_magnets

Revision ID: b1c2d3e4f5a6
Revises: aaf6a29ff703
Create Date: 2026-01-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: str | None = "aaf6a29ff703"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create lead_magnets table
    op.create_table('lead_magnets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('magnet_type', sa.String(length=50), nullable=False),
        sa.Column('delivery_method', sa.String(length=50), nullable=False),
        sa.Column('content_url', sa.String(length=500), nullable=False),
        sa.Column('thumbnail_url', sa.String(length=500), nullable=True),
        sa.Column('estimated_value', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('download_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lead_magnets_workspace_id'), 'lead_magnets', ['workspace_id'], unique=False)

    # Create offer_lead_magnets association table
    op.create_table('offer_lead_magnets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('offer_id', sa.UUID(), nullable=False),
        sa.Column('lead_magnet_id', sa.UUID(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_bonus', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['lead_magnet_id'], ['lead_magnets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['offer_id'], ['offers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('offer_id', 'lead_magnet_id', name='uq_offer_lead_magnet')
    )
    op.create_index(op.f('ix_offer_lead_magnets_lead_magnet_id'), 'offer_lead_magnets', ['lead_magnet_id'], unique=False)
    op.create_index(op.f('ix_offer_lead_magnets_offer_id'), 'offer_lead_magnets', ['offer_id'], unique=False)

    # Add Hormozi-style fields to offers table
    op.add_column('offers', sa.Column('headline', sa.String(length=500), nullable=True))
    op.add_column('offers', sa.Column('subheadline', sa.Text(), nullable=True))
    op.add_column('offers', sa.Column('regular_price', sa.Float(), nullable=True))
    op.add_column('offers', sa.Column('offer_price', sa.Float(), nullable=True))
    op.add_column('offers', sa.Column('savings_amount', sa.Float(), nullable=True))
    op.add_column('offers', sa.Column('guarantee_type', sa.String(length=50), nullable=True))
    op.add_column('offers', sa.Column('guarantee_days', sa.Integer(), nullable=True))
    op.add_column('offers', sa.Column('guarantee_text', sa.Text(), nullable=True))
    op.add_column('offers', sa.Column('urgency_type', sa.String(length=50), nullable=True))
    op.add_column('offers', sa.Column('urgency_text', sa.String(length=255), nullable=True))
    op.add_column('offers', sa.Column('scarcity_count', sa.Integer(), nullable=True))
    op.add_column('offers', sa.Column('value_stack_items', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('offers', sa.Column('cta_text', sa.String(length=100), nullable=True))
    op.add_column('offers', sa.Column('cta_subtext', sa.String(length=255), nullable=True))


def downgrade() -> None:
    # Remove Hormozi-style fields from offers table
    op.drop_column('offers', 'cta_subtext')
    op.drop_column('offers', 'cta_text')
    op.drop_column('offers', 'value_stack_items')
    op.drop_column('offers', 'scarcity_count')
    op.drop_column('offers', 'urgency_text')
    op.drop_column('offers', 'urgency_type')
    op.drop_column('offers', 'guarantee_text')
    op.drop_column('offers', 'guarantee_days')
    op.drop_column('offers', 'guarantee_type')
    op.drop_column('offers', 'savings_amount')
    op.drop_column('offers', 'offer_price')
    op.drop_column('offers', 'regular_price')
    op.drop_column('offers', 'subheadline')
    op.drop_column('offers', 'headline')

    # Drop offer_lead_magnets table
    op.drop_index(op.f('ix_offer_lead_magnets_offer_id'), table_name='offer_lead_magnets')
    op.drop_index(op.f('ix_offer_lead_magnets_lead_magnet_id'), table_name='offer_lead_magnets')
    op.drop_table('offer_lead_magnets')

    # Drop lead_magnets table
    op.drop_index(op.f('ix_lead_magnets_workspace_id'), table_name='lead_magnets')
    op.drop_table('lead_magnets')
