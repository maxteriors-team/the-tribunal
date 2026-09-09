"""Split conversation phone uniqueness by origin (native vs imported provider).

Revision ID: 20260909_conv_arbiters
Revises: 20260904_proposal_payments
Create Date: 2026-09-09

``uq_conversation_phones`` covered (workspace_id, workspace_phone_hash,
contact_phone_hash) regardless of ``source_provider``, but every native send
path looks a conversation up with ``source_provider IS NULL``. A contact whose
only thread was imported (``source_provider = 'quo'``) was therefore
unreachable: the lookup skipped the imported row, the INSERT that followed
collided with it, and the IntegrityError poisoned the worker's session.

In production that wedged the ``automation_events`` drain — events are claimed
oldest-first through one session, so a single undeliverable event starved every
lead queued behind it and two website leads went untexted for hours.

Replaces the single arbiter with two partial ones so a native thread can coexist
with an imported thread for the same phone pair, mirroring how ``messages``
already separates Quo provider identity from legacy provider identity. Both keep
the existing ``contact_phone_hash IS NOT NULL`` predicate so Messenger/Instagram
threads, which have no phone, stay out of these indexes entirely.

Metadata-only: no conversation, message, contact, or lead row is rewritten or
deleted.

Reversibility: ``downgrade`` restores the single arbiter and will fail if, by
then, a phone pair has both a native and an imported thread — exactly the state
this migration exists to permit. Reconcile those rows first.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260909_conv_arbiters"
down_revision: str | Sequence[str] | None = "20260904_proposal_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_INDEX = "uq_conversation_phones"
_NATIVE_INDEX = "uq_conversation_phones_native"
_PROVIDER_INDEX = "uq_conversation_phones_provider"

_PHONE_ROWS = "contact_phone_hash IS NOT NULL"


def upgrade() -> None:
    """Add the origin-scoped arbiters, then retire the shared one."""
    # Built concurrently so a live inbox keeps taking writes during the build;
    # concurrent index creation cannot run inside a transaction.
    with op.get_context().autocommit_block():
        op.create_index(
            _NATIVE_INDEX,
            "conversations",
            ["workspace_id", "workspace_phone_hash", "contact_phone_hash"],
            unique=True,
            postgresql_where=sa.text(f"{_PHONE_ROWS} AND source_provider IS NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            _PROVIDER_INDEX,
            "conversations",
            [
                "workspace_id",
                "source_provider",
                "workspace_phone_hash",
                "contact_phone_hash",
            ],
            unique=True,
            postgresql_where=sa.text(f"{_PHONE_ROWS} AND source_provider IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )

        # Dropped last: until this point the old arbiter still rejects duplicate
        # native threads, so there is no window without protection.
        op.drop_index(
            _LEGACY_INDEX,
            table_name="conversations",
            postgresql_concurrently=True,
            if_exists=True,
        )


def downgrade() -> None:
    """Restore the shared arbiter, then drop the origin-scoped ones."""
    with op.get_context().autocommit_block():
        op.create_index(
            _LEGACY_INDEX,
            "conversations",
            ["workspace_id", "workspace_phone_hash", "contact_phone_hash"],
            unique=True,
            postgresql_where=sa.text(_PHONE_ROWS),
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.drop_index(
            _NATIVE_INDEX,
            table_name="conversations",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            _PROVIDER_INDEX,
            table_name="conversations",
            postgresql_concurrently=True,
            if_exists=True,
        )
