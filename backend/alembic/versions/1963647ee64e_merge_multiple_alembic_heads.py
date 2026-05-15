"""merge multiple alembic heads

Revision ID: 1963647ee64e
Revises: a0b1c2d3e4f5, b2c3d4e5f6a7, rt01a1b2c3d4
Create Date: 2026-03-26 07:20:46.573488

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1963647ee64e'
down_revision: tuple[str, ...] | None = ('a0b1c2d3e4f5', 'b2c3d4e5f6a7', 'rt01a1b2c3d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
