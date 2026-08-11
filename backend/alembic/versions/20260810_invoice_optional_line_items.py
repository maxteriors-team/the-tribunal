"""add invoice optional line items

Revision ID: 20260810_inv_optional
Revises: e3a7c91d5b42
Create Date: 2026-08-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_inv_optional"
down_revision: str | Sequence[str] | None = "e3a7c91d5b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "ck_invoice_line_items_required_selected"


def upgrade() -> None:
    op.add_column(
        "invoice_line_items",
        sa.Column("is_optional", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "invoice_line_items",
        sa.Column("is_selected", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "invoice_line_items",
        "is_optional OR is_selected",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "invoice_line_items", type_="check")
    op.drop_column("invoice_line_items", "is_selected")
    op.drop_column("invoice_line_items", "is_optional")
