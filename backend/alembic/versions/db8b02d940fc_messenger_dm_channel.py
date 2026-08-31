"""Key conversations on a Meta Page-Scoped ID so DM threads can persist.

``conversations`` is a hot table, so every schema change the Messenger/Instagram
channel needs lands here in one pass rather than as a series of ALTERs.

Nothing existing is rewritten:

* the four added columns are nullable with no default, so no table rewrite and
  no backfill;
* widening the four phone columns to NULL only relaxes a constraint — every
  current row already satisfies it, which makes the downgrade a no-op for data
  that exists today;
* ``uq_conversation_phones`` changes from a UNIQUE constraint to a partial
  UNIQUE index over the same three columns. It is dropped and recreated inside
  this migration's transaction, so the uniqueness guarantee is never released
  to concurrent writers. Partial because Postgres treats every NULL as
  distinct: on Messenger rows (``contact_phone_hash IS NULL``) a full unique
  index would reject nothing and merely carry dead entries.

The downgrade refuses to run once Messenger rows exist rather than silently
dropping the column that identifies who a thread belongs to.

Revision ID: db8b02d940fc
Revises: 20260829_inbound_ai_calls
Create Date: 2026-08-30
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.encryption import EncryptedString, LookupHash

revision: str = "db8b02d940fc"
down_revision: str | None = "20260829_inbound_ai_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PHONE_UNIQUE = "uq_conversation_phones"
_PSID_UNIQUE = "uq_conversation_messenger_psid"
_PSID_LOOKUP = "ix_conversations_messenger_psid_hash"
_PHONE_COLUMNS = (
    "workspace_phone",
    "workspace_phone_hash",
    "contact_phone",
    "contact_phone_hash",
)


def upgrade() -> None:
    """Add the Messenger identity columns and relax the phone-keyed shape."""
    op.add_column(
        "conversations",
        sa.Column("messenger_psid", EncryptedString(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("messenger_psid_hash", LookupHash(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("messenger_display_name", EncryptedString(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("messenger_window_expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    for column in _PHONE_COLUMNS:
        op.alter_column("conversations", column, existing_type=sa.TEXT(), nullable=True)

    op.drop_constraint(_PHONE_UNIQUE, "conversations", type_="unique")
    op.create_index(
        _PHONE_UNIQUE,
        "conversations",
        ["workspace_id", "workspace_phone_hash", "contact_phone_hash"],
        unique=True,
        postgresql_where=sa.text("contact_phone_hash IS NOT NULL"),
    )

    op.create_index(_PSID_LOOKUP, "conversations", ["messenger_psid_hash"], unique=False)
    op.create_index(
        _PSID_UNIQUE,
        "conversations",
        ["workspace_id", "messenger_psid_hash"],
        unique=True,
        postgresql_where=sa.text("messenger_psid_hash IS NOT NULL"),
    )


def downgrade() -> None:
    """Restore the phone-only shape without silently destroying DM threads.

    Restoring ``NOT NULL`` on the phone columns is impossible while phone-less
    Messenger rows exist, so this stops and names them rather than letting
    Postgres fail with a constraint error that reads like a bug.

    The override exists because a migration you cannot reverse is its own
    outage: during an incident an operator must be able to roll back. Setting
    ``MESSENGER_DOWNGRADE_DELETE_DM_THREADS=1`` deletes those threads, which is
    destructive and therefore never the default.
    """
    bind = op.get_bind()
    doomed = sa.text(
        "SELECT count(*) FROM conversations "
        "WHERE messenger_psid_hash IS NOT NULL OR contact_phone_hash IS NULL"
    )
    remaining = bind.execute(doomed).scalar_one()
    if remaining:
        if os.environ.get("MESSENGER_DOWNGRADE_DELETE_DM_THREADS") != "1":
            raise RuntimeError(
                f"{remaining} conversation(s) have no phone number, so the phone "
                "columns cannot go back to NOT NULL. Their messages and the "
                "Page-Scoped ID identifying who they belong to would be lost.\n"
                "Export them first, then re-run with "
                "MESSENGER_DOWNGRADE_DELETE_DM_THREADS=1 to delete them."
            )
        bind.execute(
            sa.text(
                "DELETE FROM conversations "
                "WHERE messenger_psid_hash IS NOT NULL OR contact_phone_hash IS NULL"
            )
        )

    op.drop_index(
        _PSID_UNIQUE,
        table_name="conversations",
        postgresql_where=sa.text("messenger_psid_hash IS NOT NULL"),
    )
    op.drop_index(_PSID_LOOKUP, table_name="conversations")
    op.drop_index(
        _PHONE_UNIQUE,
        table_name="conversations",
        postgresql_where=sa.text("contact_phone_hash IS NOT NULL"),
    )
    op.create_unique_constraint(
        _PHONE_UNIQUE,
        "conversations",
        ["workspace_id", "workspace_phone_hash", "contact_phone_hash"],
    )

    for column in reversed(_PHONE_COLUMNS):
        op.alter_column("conversations", column, existing_type=sa.TEXT(), nullable=False)

    op.drop_column("conversations", "messenger_window_expires_at")
    op.drop_column("conversations", "messenger_display_name")
    op.drop_column("conversations", "messenger_psid_hash")
    op.drop_column("conversations", "messenger_psid")
