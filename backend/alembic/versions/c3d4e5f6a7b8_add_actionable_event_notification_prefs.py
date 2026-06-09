"""Add per-user actionable-event notification preference columns.

Adds per-type opt-out toggles for the new actionable-event notifications
(reviews, deal-coach at-risk alerts, missed-call text-back, roleplay runs,
and automation triggers). These gate both push and email delivery for the
matching ``notification_type``.

Revision ID: c3d4e5f6a7b8
Revises: 20260612_automation_events
Create Date: 2026-06-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "20260612_automation_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_COLUMNS = (
    "notification_push_reviews",
    "notification_push_deal_alerts",
    "notification_push_missed_call_textback",
    "notification_push_roleplay",
    "notification_push_automations",
)


def upgrade() -> None:
    for column in _NEW_COLUMNS:
        op.add_column(
            "users",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    for column in reversed(_NEW_COLUMNS):
        op.drop_column("users", column)
