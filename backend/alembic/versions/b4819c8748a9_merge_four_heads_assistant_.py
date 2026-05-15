"""Merge four heads.

Unifies assistant conversations, SMS link clicks, inbound SMS idempotency,
and contact engagement composite index branches.

Revision ID: b4819c8748a9
Revises: a9b0c1d2e3f4, a9b0c1d2e3f5, ed05a7b8c9d0, f1a2b3c4d5e7
Create Date: 2026-05-14 21:21:52.391224

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'b4819c8748a9'
down_revision: str | None = ('a9b0c1d2e3f4', 'a9b0c1d2e3f5', 'ed05a7b8c9d0', 'f1a2b3c4d5e7')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
