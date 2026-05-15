"""add_contact_address_fields

Revision ID: b3c4d5e6f7a8
Revises: 79a0808ae761
Create Date: 2026-04-08 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ca01b2c3d4e5'
down_revision: str | None = "79a0808ae761"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('address_line1', sa.String(length=255), nullable=True))
    op.add_column('contacts', sa.Column('address_line2', sa.String(length=255), nullable=True))
    op.add_column('contacts', sa.Column('address_city', sa.String(length=100), nullable=True))
    op.add_column('contacts', sa.Column('address_state', sa.String(length=50), nullable=True))
    op.add_column('contacts', sa.Column('address_zip', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('contacts', 'address_zip')
    op.drop_column('contacts', 'address_state')
    op.drop_column('contacts', 'address_city')
    op.drop_column('contacts', 'address_line2')
    op.drop_column('contacts', 'address_line1')
