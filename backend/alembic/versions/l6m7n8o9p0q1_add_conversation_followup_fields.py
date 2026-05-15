"""add conversation followup fields

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-01-18 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l6m7n8o9p0q1'
down_revision: str | None = "k5l6m7n8o9p0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add follow-up fields to conversations table."""
    op.add_column(
        'conversations',
        sa.Column('followup_enabled', sa.Boolean(), nullable=False, server_default='false')
    )
    op.add_column(
        'conversations',
        sa.Column('followup_delay_hours', sa.Integer(), nullable=False, server_default='24')
    )
    op.add_column(
        'conversations',
        sa.Column('followup_max_count', sa.Integer(), nullable=False, server_default='3')
    )
    op.add_column(
        'conversations',
        sa.Column('followup_count_sent', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column(
        'conversations',
        sa.Column('next_followup_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'conversations',
        sa.Column('last_followup_at', sa.DateTime(timezone=True), nullable=True)
    )
    # Add index for efficient querying by the followup worker
    op.create_index(
        'ix_conversations_next_followup_at',
        'conversations',
        ['next_followup_at'],
        unique=False
    )


def downgrade() -> None:
    """Remove follow-up fields from conversations table."""
    op.drop_index('ix_conversations_next_followup_at', table_name='conversations')
    op.drop_column('conversations', 'last_followup_at')
    op.drop_column('conversations', 'next_followup_at')
    op.drop_column('conversations', 'followup_count_sent')
    op.drop_column('conversations', 'followup_max_count')
    op.drop_column('conversations', 'followup_delay_hours')
    op.drop_column('conversations', 'followup_enabled')
