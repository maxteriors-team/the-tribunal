"""Let managers choose Lighting League participants.

Revision ID: 20260904_scoreboard_selection
Revises: 20260903_inventory_services
Create Date: 2026-09-04

Existing and new technicians remain selected by default, preserving current
standings until a manager explicitly turns participation off.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260904_scoreboard_selection"
down_revision: str | None = "20260903_inventory_services"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a forward-safe, default-on participation control."""
    op.add_column(
        "technicians",
        sa.Column(
            "scoreboard_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    """Remove the participation control in disposable rollback-test databases."""
    op.drop_column("technicians", "scoreboard_enabled")
