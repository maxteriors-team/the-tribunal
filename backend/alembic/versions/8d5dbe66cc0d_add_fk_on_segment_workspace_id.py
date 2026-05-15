"""add FK on segment workspace_id

Revision ID: 8d5dbe66cc0d
Revises: c5d6e7f8a9b0
Create Date: 2026-05-15 12:27:11.122508

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8d5dbe66cc0d'
down_revision: Union[str, None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_foreign_key(
        'fk_segments_workspace_id_workspaces',
        'segments',
        'workspaces',
        ['workspace_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_segments_workspace_id_workspaces',
        'segments',
        type_='foreignkey',
    )
