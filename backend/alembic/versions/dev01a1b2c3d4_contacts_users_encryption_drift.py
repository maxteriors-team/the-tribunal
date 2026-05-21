"""dev-only: align contacts/users PII columns with the encryption refactor.

The ORM expects ``contacts.email``/``phone_number`` and
``users.email``/``phone_number`` to be ``EncryptedString`` (TEXT) with a
companion ``LookupHash`` column (``email_hash`` / ``phone_hash``) for
deterministic lookups. The migrations that introduced encryption never
landed for these two tables, so a freshly-migrated dev DB drifts from the
ORM and every SELECT against ``Contact`` or ``User`` fails with
``column ... does not exist``.

This migration is conservative on purpose:
- Only touches ``contacts`` and ``users``.
- Adds the hash columns and widens email/phone to TEXT.
- Drops the now-unused VARCHAR indexes that the ORM no longer declares.
- Does NOT re-encrypt existing rows; it assumes the table is empty (true
  for any fresh dev DB) or that any existing rows are short enough to fit
  TEXT (they already are — VARCHAR is just TEXT with a length cap).

Revision ID: dev01a1b2c3d4
Revises: cc1d2e3f4a5b
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "dev01a1b2c3d4"
down_revision: str | Sequence[str] | None = "cc1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # contacts: widen PII columns to TEXT and add lookup hashes.
    op.alter_column("contacts", "email", type_=sa.Text(), existing_nullable=True)
    op.alter_column("contacts", "phone_number", type_=sa.Text(), existing_nullable=False)
    op.add_column("contacts", sa.Column("email_hash", sa.Text(), nullable=True))
    # ``phone_hash`` is NOT NULL in the ORM; the table is empty in dev so we
    # can add it without a backfill default. If a non-empty dev DB hits this
    # migration, it'll need to backfill ``hash_value(phone_number)`` first.
    op.add_column("contacts", sa.Column("phone_hash", sa.Text(), nullable=False))
    op.create_index("ix_contacts_email_hash", "contacts", ["email_hash"], unique=False)
    op.create_index("ix_contacts_phone_hash", "contacts", ["phone_hash"], unique=False)
    # Drop indexes the ORM no longer declares — the lookup hashes replace them.
    op.execute('DROP INDEX IF EXISTS "ix_contacts_email"')
    op.execute('DROP INDEX IF EXISTS "ix_contacts_phone_number"')

    # users: same shape — email is NOT NULL UNIQUE, phone is nullable.
    op.alter_column("users", "email", type_=sa.Text(), existing_nullable=False)
    op.alter_column("users", "phone_number", type_=sa.Text(), existing_nullable=True)
    op.add_column("users", sa.Column("email_hash", sa.Text(), nullable=False))
    op.add_column("users", sa.Column("phone_hash", sa.Text(), nullable=True))
    op.create_index("ix_users_email_hash", "users", ["email_hash"], unique=True)
    op.create_index("ix_users_phone_hash", "users", ["phone_hash"], unique=False)
    op.execute('DROP INDEX IF EXISTS "ix_users_email"')


def downgrade() -> None:
    # users — reverse first so types come back symmetric.
    op.execute('DROP INDEX IF EXISTS "ix_users_phone_hash"')
    op.execute('DROP INDEX IF EXISTS "ix_users_email_hash"')
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.drop_column("users", "phone_hash")
    op.drop_column("users", "email_hash")
    op.alter_column("users", "phone_number", type_=sa.String(length=50), existing_nullable=True)
    op.alter_column("users", "email", type_=sa.String(length=255), existing_nullable=False)

    # contacts.
    op.execute('DROP INDEX IF EXISTS "ix_contacts_phone_hash"')
    op.execute('DROP INDEX IF EXISTS "ix_contacts_email_hash"')
    op.create_index("ix_contacts_phone_number", "contacts", ["phone_number"], unique=False)
    op.create_index("ix_contacts_email", "contacts", ["email"], unique=False)
    op.drop_column("contacts", "phone_hash")
    op.drop_column("contacts", "email_hash")
    op.alter_column(
        "contacts", "phone_number", type_=sa.String(length=20), existing_nullable=False
    )
    op.alter_column("contacts", "email", type_=sa.String(length=255), existing_nullable=True)
