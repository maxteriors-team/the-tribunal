"""add_user_settings_fields

Revision ID: aaf6a29ff703
Revises: add_automations_001
Create Date: 2026-01-02 19:13:39.442435

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'aaf6a29ff703'
down_revision: str | None = "add_automations_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add user settings columns with server defaults for existing rows
    op.add_column('users', sa.Column('phone_number', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('timezone', sa.String(length=100), nullable=False, server_default='America/New_York'))
    op.add_column('users', sa.Column('notification_email', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('users', sa.Column('notification_sms', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('users', sa.Column('notification_push', sa.Boolean(), nullable=False, server_default='true'))


def downgrade() -> None:
    op.drop_column('users', 'notification_push')
    op.drop_column('users', 'notification_sms')
    op.drop_column('users', 'notification_email')
    op.drop_column('users', 'timezone')
    op.drop_column('users', 'phone_number')
