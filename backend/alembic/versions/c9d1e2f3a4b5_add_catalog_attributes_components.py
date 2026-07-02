"""add catalog_items attributes + components

Adds two nullable JSONB columns to ``catalog_items`` so a catalog entry can carry
what a fixture/service needs beyond a price, without a schema change per business:

* ``attributes`` \u2014 free-form flags (e.g. ``{"transformer": true}`` to exclude a
  fixture from the Care Plan count, ``{"per_linear_foot": true}`` for string
  lighting). Config behaviour, not new columns.
* ``components`` \u2014 the internal SKU bill-of-materials for the fulfillment sheet:
  a list of ``{"sku", "description", "qty"}`` parts per unit. Never client-facing.

Both are additive and nullable, so existing rows are untouched and the change is
fully reversible.

Revision ID: c9d1e2f3a4b5
Revises: 02ad3fc109e7
Create Date: 2026-07-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d1e2f3a4b5"
down_revision: Union[str, None] = "02ad3fc109e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalog_items",
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "catalog_items",
        sa.Column("components", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("catalog_items", "components")
    op.drop_column("catalog_items", "attributes")
