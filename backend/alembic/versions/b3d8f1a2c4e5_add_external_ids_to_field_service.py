"""add external source/id to crews and technicians

Adds nullable ``external_source`` + ``external_id`` columns to ``crews`` and
``technicians`` so records imported from an external system (e.g. Jobber
``users``) carry a stable provenance key. A partial unique index on
``(workspace_id, external_source, external_id)`` makes the Jobber sync
idempotent: re-running it upserts the same rows instead of creating duplicates.
Natively-created records leave both columns null and are excluded from the
unique index by the ``external_id IS NOT NULL`` predicate.

Revision ID: b3d8f1a2c4e5
Revises: 5661478c9c9e
Create Date: 2026-06-27 01:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d8f1a2c4e5'
down_revision: Union[str, None] = '5661478c9c9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("crews", "technicians"):
        op.add_column(table, sa.Column("external_source", sa.String(length=50), nullable=True))
        op.add_column(table, sa.Column("external_id", sa.String(length=255), nullable=True))
        op.create_index(
            f"uq_{table}_workspace_external",
            table,
            ["workspace_id", "external_source", "external_id"],
            unique=True,
            postgresql_where=sa.text("external_id IS NOT NULL"),
        )


def downgrade() -> None:
    for table in ("crews", "technicians"):
        op.drop_index(f"uq_{table}_workspace_external", table_name=table)
        op.drop_column(table, "external_id")
        op.drop_column(table, "external_source")
