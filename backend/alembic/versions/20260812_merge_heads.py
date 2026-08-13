"""merge reminder-channel and lighting-project heads

Revision ID: 20260812_merge_heads
Revises: 20260811_lighting_handoff, 20260811_reminder_channels
Create Date: 2026-08-12 11:59:00.000000
"""

from collections.abc import Sequence

revision: str = "20260812_merge_heads"
down_revision: str | Sequence[str] | None = (
    "20260811_lighting_handoff",
    "20260811_reminder_channels",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the concurrent schema branches."""


def downgrade() -> None:
    """Restore the concurrent branch heads."""
