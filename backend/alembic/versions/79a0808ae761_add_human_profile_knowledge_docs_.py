"""add_human_profile_knowledge_docs_pending_actions

Revision ID: 79a0808ae761
Revises: e4047b1e53a9
Create Date: 2026-04-08 09:13:34.180624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '79a0808ae761'
down_revision: str | None = "e4047b1e53a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('human_profiles',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('role_title', sa.String(length=255), nullable=True),
    sa.Column('phone_number', sa.String(length=50), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('timezone', sa.String(length=100), nullable=False),
    sa.Column('bio', sa.Text(), nullable=True),
    sa.Column('communication_preferences', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('action_policies', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('default_policy', sa.String(length=20), nullable=False),
    sa.Column('auto_approve_timeout_minutes', sa.Integer(), nullable=False),
    sa.Column('auto_reject_timeout_minutes', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_human_profiles_agent_id'), 'human_profiles', ['agent_id'], unique=True)
    op.create_index(op.f('ix_human_profiles_workspace_id'), 'human_profiles', ['workspace_id'], unique=False)
    op.create_table('knowledge_documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('doc_type', sa.String(length=50), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_documents_agent_id'), 'knowledge_documents', ['agent_id'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_workspace_id'), 'knowledge_documents', ['workspace_id'], unique=False)
    op.create_table('pending_actions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('action_type', sa.String(length=100), nullable=False),
    sa.Column('action_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('urgency', sa.String(length=20), nullable=False),
    sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_channel', sa.String(length=20), nullable=True),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('execution_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notification_sent', sa.Boolean(), nullable=False),
    sa.Column('notification_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pending_actions_action_type'), 'pending_actions', ['action_type'], unique=False)
    op.create_index(op.f('ix_pending_actions_agent_id'), 'pending_actions', ['agent_id'], unique=False)
    op.create_index(op.f('ix_pending_actions_expires_at'), 'pending_actions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_pending_actions_status'), 'pending_actions', ['status'], unique=False)
    op.create_index(op.f('ix_pending_actions_workspace_id'), 'pending_actions', ['workspace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_pending_actions_workspace_id'), table_name='pending_actions')
    op.drop_index(op.f('ix_pending_actions_status'), table_name='pending_actions')
    op.drop_index(op.f('ix_pending_actions_expires_at'), table_name='pending_actions')
    op.drop_index(op.f('ix_pending_actions_agent_id'), table_name='pending_actions')
    op.drop_index(op.f('ix_pending_actions_action_type'), table_name='pending_actions')
    op.drop_table('pending_actions')
    op.drop_index(op.f('ix_knowledge_documents_workspace_id'), table_name='knowledge_documents')
    op.drop_index(op.f('ix_knowledge_documents_agent_id'), table_name='knowledge_documents')
    op.drop_table('knowledge_documents')
    op.drop_index(op.f('ix_human_profiles_workspace_id'), table_name='human_profiles')
    op.drop_index(op.f('ix_human_profiles_agent_id'), table_name='human_profiles')
    op.drop_table('human_profiles')
