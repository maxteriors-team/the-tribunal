"""Add service plan fields to recurring_job_templates.

Turns the generic maintenance-contract template into a **Service Plan**: the
persisted record of what a client actually signed up for. ``plan_type``
distinguishes a landscape-lighting Care Plan from a seasonal Christmas signup
from a hand-built maintenance contract, ``care_plan_tier`` carries the tier the
client picked on their proposal, and ``source_quote_id`` records the approved
quote the plan was provisioned from.

Existing rows backfill to ``maintenance`` through the server default, so no data
rewrite is needed. The partial unique index on
``(source_quote_id, plan_type, title)`` is the authoritative guard against
double-provisioning: re-approving a quote (operator retry, client double-click)
must be a no-op, not a second signup. ``title`` is part of the key because a
Christmas signup provisions an install *and* a takedown plan that share both the
quote and the plan type.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9d98a9f7882"
down_revision: str | None = "b2d5f8a1c034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "recurring_job_templates"
PLAN_TYPE_INDEX = "ix_recurring_job_templates_workspace_plan_type"
SOURCE_QUOTE_INDEX = "uq_recurring_job_templates_source_quote_plan"
SOURCE_QUOTE_FK = "fk_recurring_job_templates_source_quote_id_quotes"
SOURCE_QUOTE_WHERE = sa.text("source_quote_id IS NOT NULL")


def upgrade() -> None:
    op.add_column(
        TABLE_NAME,
        sa.Column(
            "plan_type",
            sa.String(length=32),
            server_default="maintenance",
            nullable=False,
        ),
    )
    op.add_column(TABLE_NAME, sa.Column("care_plan_tier", sa.String(length=64), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("source_quote_id", sa.UUID(), nullable=True))
    op.create_index(PLAN_TYPE_INDEX, TABLE_NAME, ["workspace_id", "plan_type"], unique=False)
    op.create_index(
        SOURCE_QUOTE_INDEX,
        TABLE_NAME,
        ["source_quote_id", "plan_type", "title"],
        unique=True,
        postgresql_where=SOURCE_QUOTE_WHERE,
    )
    op.create_foreign_key(
        SOURCE_QUOTE_FK,
        TABLE_NAME,
        "quotes",
        ["source_quote_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(SOURCE_QUOTE_FK, TABLE_NAME, type_="foreignkey")
    op.drop_index(SOURCE_QUOTE_INDEX, table_name=TABLE_NAME, postgresql_where=SOURCE_QUOTE_WHERE)
    op.drop_index(PLAN_TYPE_INDEX, table_name=TABLE_NAME)
    op.drop_column(TABLE_NAME, "source_quote_id")
    op.drop_column(TABLE_NAME, "care_plan_tier")
    op.drop_column(TABLE_NAME, "plan_type")
