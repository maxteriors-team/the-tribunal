"""add speed-to-lead first response tracking to conversations

Revision ID: 7bafc8edd369
Revises: 20260605_roleplay_arena
Create Date: 2026-06-05 20:30:30.426025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7bafc8edd369'
down_revision: Union[str, None] = '20260605_roleplay_arena'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Speed-to-lead SLA: first-response tracking on conversations.
    op.add_column(
        'conversations',
        sa.Column('first_inbound_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'conversations',
        sa.Column('first_response_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'conversations',
        sa.Column('first_response_seconds', sa.Integer(), nullable=True),
    )
    op.create_index(
        'ix_conversations_workspace_first_response_at',
        'conversations',
        ['workspace_id', 'first_response_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_conversations_workspace_first_response_at',
        table_name='conversations',
    )
    op.drop_column('conversations', 'first_response_seconds')
    op.drop_column('conversations', 'first_response_at')
    op.drop_column('conversations', 'first_inbound_at')
