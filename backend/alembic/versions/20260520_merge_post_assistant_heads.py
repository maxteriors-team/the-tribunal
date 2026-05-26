"""Merge three heads after assistant + post-assistant migrations.

No-op merge that unifies the branches left after several feature migrations
were authored in parallel.

Branches merged:

- ``20260520_mac_relay_sender_fields`` — Mac relay phone-number columns.
- ``9a01178f7789`` — conversations.contact_id ON DELETE CASCADE alignment.
- ``dlq01a1b2c3d4`` — failed_jobs DLQ table.

The two ex-duplicate ``a9b0c1d2e3f4`` siblings (``bb1c2d3e4f5a`` FK indexes
and ``cc1d2e3f4a5b`` avatar_url) chain AFTER this merge because their
DDL touches tables created by later feature branches (``invitations``,
``opportunities``, etc.); running them on the merged schema is the only
order that satisfies their references.

Revision ID: 20260520_merge_post_heads
Revises: 20260520_mac_relay_sender_fields, 9a01178f7789, dlq01a1b2c3d4
Create Date: 2026-05-20 17:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20260520_merge_post_heads"
down_revision: tuple[str, ...] | None = (
    "20260520_mac_relay_sender_fields",
    "9a01178f7789",
    "dlq01a1b2c3d4",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op merge."""


def downgrade() -> None:
    """No-op merge."""
