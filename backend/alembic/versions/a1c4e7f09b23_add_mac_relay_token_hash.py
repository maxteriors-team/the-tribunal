"""Add per-workspace Mac relay token digest.

Closes audit finding H-4 (``docs/security-audit-2026-07-27.md``).

The relay webhook previously accepted a single *global* bearer token and then
derived the tenant from the request body. That token ships to every
customer-operated Mac, so one compromised relay host could write messages into
any workspace — and, because the body's ``from`` was equally attacker-chosen,
do it *as* another tenant's operator.

This adds the column that makes the token itself the tenancy decision: a relay
host presents a token minted for one ``phone_numbers`` row, and that row's
``workspace_id`` scopes every downstream lookup.

Only the SHA-256 hex digest is stored (64 chars), mirroring
``api_keys.key_hash`` — plaintext exists once, at issue time. The column is
uniquely indexed because the digest *is* the lookup key: two rows sharing one
would make tenant resolution ambiguous.

Nullable and unique coexist fine here — Postgres treats NULLs as distinct in a
unique index, so every workspace that has not yet been issued a relay token
stays NULL without colliding.

Revision ID: a1c4e7f09b23
Revises: d79ddb8ae80b
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c4e7f09b23"
down_revision: str | Sequence[str] | None = "d79ddb8ae80b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "phone_numbers"
_COLUMN = "mac_relay_token_hash"
_INDEX = "ix_phone_numbers_mac_relay_token_hash"


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return

    existing = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if _COLUMN not in existing:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=64), nullable=True))

    indexes = {i["name"] for i in sa.inspect(bind).get_indexes(_TABLE)}
    if _INDEX not in indexes:
        op.create_index(_INDEX, _TABLE, [_COLUMN], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return

    op.execute(f'DROP INDEX IF EXISTS "{_INDEX}"')

    existing = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if _COLUMN in existing:
        op.drop_column(_TABLE, _COLUMN)
