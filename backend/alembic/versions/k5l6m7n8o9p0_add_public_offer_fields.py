"""add_public_offer_fields

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-01-18 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'k5l6m7n8o9p0'
down_revision: str | None = "j4k5l6m7n8o9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add public landing page fields to offers
    op.add_column('offers', sa.Column('is_public', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('offers', sa.Column('public_slug', sa.String(length=100), nullable=True))
    op.add_column('offers', sa.Column('require_email', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('offers', sa.Column('require_phone', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('offers', sa.Column('require_name', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('offers', sa.Column('page_views', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('offers', sa.Column('opt_ins', sa.Integer(), nullable=False, server_default='0'))

    # Create unique index on public_slug
    op.create_index(op.f('ix_offers_public_slug'), 'offers', ['public_slug'], unique=True)


def downgrade() -> None:
    # Drop public fields from offers
    op.drop_index(op.f('ix_offers_public_slug'), table_name='offers')
    op.drop_column('offers', 'opt_ins')
    op.drop_column('offers', 'page_views')
    op.drop_column('offers', 'require_name')
    op.drop_column('offers', 'require_phone')
    op.drop_column('offers', 'require_email')
    op.drop_column('offers', 'public_slug')
    op.drop_column('offers', 'is_public')
