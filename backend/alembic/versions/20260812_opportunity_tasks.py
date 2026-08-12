"""add opportunity tasks

Revision ID: 20260812_opportunity_tasks
Revises: 20260812_training_examples
Create Date: 2026-08-12 18:14:46.823777

New table only -- no existing row is read or rewritten, so this is safe against
the live CRM data in ``opportunities``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260812_opportunity_tasks"
down_revision: str | Sequence[str] | None = "20260812_training_examples"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('opportunity_tasks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('opportunity_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_by_id', sa.Integer(), nullable=True),
    sa.Column('assigned_user_id', sa.Integer(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['assigned_user_id'], ['users.id'], name=op.f('fk_opportunity_tasks_assigned_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['completed_by_id'], ['users.id'], name=op.f('fk_opportunity_tasks_completed_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_opportunity_tasks_created_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id'], name=op.f('fk_opportunity_tasks_opportunity_id_opportunities'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_opportunity_tasks'))
    )
    op.create_index(op.f('ix_opportunity_tasks_assigned_user_id'), 'opportunity_tasks', ['assigned_user_id'], unique=False)
    op.create_index(op.f('ix_opportunity_tasks_completed_at'), 'opportunity_tasks', ['completed_at'], unique=False)
    op.create_index(op.f('ix_opportunity_tasks_due_at'), 'opportunity_tasks', ['due_at'], unique=False)
    op.create_index(op.f('ix_opportunity_tasks_opportunity_id'), 'opportunity_tasks', ['opportunity_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_opportunity_tasks_opportunity_id'), table_name='opportunity_tasks')
    op.drop_index(op.f('ix_opportunity_tasks_due_at'), table_name='opportunity_tasks')
    op.drop_index(op.f('ix_opportunity_tasks_completed_at'), table_name='opportunity_tasks')
    op.drop_index(op.f('ix_opportunity_tasks_assigned_user_id'), table_name='opportunity_tasks')
    op.drop_table('opportunity_tasks')
