"""add reminder channels, confirmation email toggle, and email reminder tracking

Revision ID: 20260811_reminder_channels
Revises: 20260811_lighting_projects
Create Date: 2026-08-11 00:00:03.000000

Additive only: ``appointments`` holds live CRM data, so every column lands with a
server default rather than a backfill, and existing agents keep SMS-only
reminders because ``reminder_channels`` defaults to ``{sms}``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260811_reminder_channels"
down_revision: str | Sequence[str] | None = "20260811_lighting_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column(
            "reminders_sent_email",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "reminder_channels",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{sms}",
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "confirmation_email_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "confirmation_email_enabled")
    op.drop_column("agents", "reminder_channels")
    op.drop_column("appointments", "reminders_sent_email")
