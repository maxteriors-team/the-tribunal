"""add partial-unique index for recurring job occurrences

Makes recurring-job materialization race-safe. The worker previously relied on an
in-process SELECT-then-INSERT check, which is a TOCTOU race: two overlapping
runs (a tick racing an operator "generate next now", or multiple app replicas)
could both pass the check and create duplicate jobs for the same occurrence.

This partial-unique index on ``(recurring_template_id, scheduled_start)`` (only
where ``recurring_template_id IS NOT NULL``) is the authoritative guard — the
loser of a concurrent insert gets an IntegrityError and skips.

Revision ID: 7c1e9a4b2f30
Revises: 05ee4fe87849
Create Date: 2026-06-29
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "7c1e9a4b2f30"
down_revision: Union[str, None] = "05ee4fe87849"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_field_service_jobs_recurring_occurrence",
        "field_service_jobs",
        ["recurring_template_id", "scheduled_start"],
        unique=True,
        postgresql_where=sa.text("recurring_template_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_field_service_jobs_recurring_occurrence",
        table_name="field_service_jobs",
    )
