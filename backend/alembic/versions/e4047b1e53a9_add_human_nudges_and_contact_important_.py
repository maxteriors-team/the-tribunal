"""add_human_nudges_and_contact_important_dates

Revision ID: e4047b1e53a9
Revises: arl01a1b2c3d4
Create Date: 2026-03-28 17:25:38.570420

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e4047b1e53a9'
down_revision: str | None = "arl01a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create human_nudges table
    op.create_table('human_nudges',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('nudge_type', sa.String(length=50), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('suggested_action', sa.String(length=50), nullable=True),
    sa.Column('priority', sa.String(length=20), nullable=False),
    sa.Column('due_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source_date_field', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('snoozed_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_via', sa.String(length=20), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('assigned_to_user_id', sa.Integer(), nullable=True),
    sa.Column('dedup_key', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_human_nudges_contact_id'), 'human_nudges', ['contact_id'], unique=False)
    op.create_index(op.f('ix_human_nudges_dedup_key'), 'human_nudges', ['dedup_key'], unique=True)
    op.create_index(op.f('ix_human_nudges_due_date'), 'human_nudges', ['due_date'], unique=False)
    op.create_index(op.f('ix_human_nudges_nudge_type'), 'human_nudges', ['nudge_type'], unique=False)
    op.create_index(op.f('ix_human_nudges_status'), 'human_nudges', ['status'], unique=False)
    op.create_index(op.f('ix_human_nudges_workspace_id'), 'human_nudges', ['workspace_id'], unique=False)

    # Add important_dates JSONB column to contacts
    op.add_column('contacts', sa.Column('important_dates', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('contacts', 'important_dates')
    op.drop_index(op.f('ix_human_nudges_workspace_id'), table_name='human_nudges')
    op.drop_index(op.f('ix_human_nudges_status'), table_name='human_nudges')
    op.drop_index(op.f('ix_human_nudges_nudge_type'), table_name='human_nudges')
    op.drop_index(op.f('ix_human_nudges_due_date'), table_name='human_nudges')
    op.drop_index(op.f('ix_human_nudges_dedup_key'), table_name='human_nudges')
    op.drop_index(op.f('ix_human_nudges_contact_id'), table_name='human_nudges')
    op.drop_table('human_nudges')
