"""add quote public_token

Adds ``quotes.public_token``: a nullable, unique, indexed URL-safe token that
keys the no-auth client proposal page (``/p/quotes/{token}``) and its
approve/decline actions. Null until a quote is first sent — drafts have no token
and never resolve publicly. Backfill is intentionally omitted: existing sent
quotes get a token the next time they are (re-)sent.

Revision ID: 02ad3fc109e7
Revises: e7f8a9b0c1d2
Create Date: 2026-07-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "02ad3fc109e7"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("quotes", sa.Column("public_token", sa.String(length=64), nullable=True))
    op.create_index(
        op.f("ix_quotes_public_token"), "quotes", ["public_token"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_quotes_public_token"), table_name="quotes")
    op.drop_column("quotes", "public_token")
