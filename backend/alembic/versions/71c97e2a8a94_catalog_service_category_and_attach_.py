"""Add service category and attach fields to catalog_items.

Revision ID: 71c97e2a8a94
Revises: a9d98a9f7882
Create Date: 2026-07-29 10:44:21.040565

The price book could not tell a roof apart from gutters, so attach-rate
reporting ("how often does a gutter add-on ride along with a roof job?") had
nothing to group by. ``service_category`` supplies that grouping, ``is_attachable``
marks the add-ons that form the numerator, and ``attach_targets`` records which
categories an add-on belongs with (``{"roof"}`` on a gutter guard).

Purely additive and safe on existing rows: ``service_category`` is nullable, so
existing items read as uncategorized until an operator classifies them (reporting
treats NULL as unknown, not as a category), and the two NOT NULL columns backfill
through server defaults (``false`` / empty array) without a data rewrite.

``service_category`` is a plain ``VARCHAR``, deliberately not an enum: workspaces
run trades we did not enumerate and must be able to use their own categories
without a migration. The index supports grouping by category in reporting.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "71c97e2a8a94"
down_revision: str | None = "a9d98a9f7882"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "catalog_items"
CATEGORY_INDEX = "ix_catalog_items_service_category"


def upgrade() -> None:
    op.add_column(TABLE_NAME, sa.Column("service_category", sa.String(length=60), nullable=True))
    op.add_column(
        TABLE_NAME,
        sa.Column("is_attachable", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        TABLE_NAME,
        sa.Column(
            "attach_targets",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.create_index(CATEGORY_INDEX, TABLE_NAME, ["service_category"], unique=False)


def downgrade() -> None:
    op.drop_index(CATEGORY_INDEX, table_name=TABLE_NAME)
    op.drop_column(TABLE_NAME, "attach_targets")
    op.drop_column(TABLE_NAME, "is_attachable")
    op.drop_column(TABLE_NAME, "service_category")
