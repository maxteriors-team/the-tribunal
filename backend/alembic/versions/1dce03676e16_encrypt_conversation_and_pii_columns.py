"""Encrypt conversation/message PII and the remaining plaintext PII tables.

Closes audit findings H-1 and H-2 (``docs/security-audit-2026-07-27.md``).

Before this migration, ``contacts.phone_number`` was Fernet-encrypted while the
*same* phone number sat in plaintext (and indexed) on ``conversations``, next to
every SMS body, email body, and AI call transcript. Anyone with a database read
primitive — a stolen backup, a compromised replica, a leaked ``DATABASE_URL`` —
could read the whole customer corpus in cleartext without touching the key.
``global_opt_outs`` (the TCPA suppression list) and ``lead_magnet_leads`` were
likewise plaintext and indexed.

Shape of the change, per column:

* Content columns (message bodies, transcripts, previews, summaries) simply
  become :class:`~app.core.encryption.EncryptedString`. Verified beforehand that
  nothing filters, sorts, or full-text-searches them, so ciphertext at rest
  costs nothing. (The one ``to_tsvector`` index in the schema is on
  ``knowledge_chunks.content``, a different table, and is untouched.)
* Identifier columns (phones, emails) additionally gain a deterministic
  ``*_hash`` sibling that carries the index and any uniqueness. Fernet is
  non-deterministic, so an index or ``UNIQUE`` on the ciphertext is useless:
  the same phone encrypts differently every write.

Two constraints therefore move onto hashes: ``uq_conversation_phones`` and
``uq_workspace_opt_out``. ``ix_demo_requests_phone_created_at`` is re-pointed
for the same reason — it backs the demo rate-limit window scan and would
otherwise silently go dead.

NORMALIZATION HAZARD (pre-flight checked below): ``hash_phone`` strips
formatting before hashing, so ``+15551234567`` and ``(555) 123-4567`` — two
distinct rows under the old plaintext constraints — collapse to one hash. Rather
than discover that as an ``IntegrityError`` halfway through encrypting a
production table, :func:`_assert_no_hash_collisions` fails fast, before any data
is mutated, naming the rows to reconcile.

Revision ID: 1dce03676e16
Revises: 7c5a23b17a86
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.encryption import (
    _get_fernet,
    hash_phone,
    hash_value,
)

revision: str = "1dce03676e16"
down_revision: str | Sequence[str] | None = "7c5a23b17a86"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --------------------------------------------------------------------------
# Column inventory
# --------------------------------------------------------------------------

#: ``table -> columns`` that only need their values encrypted. No lookup hash,
#: because nothing queries them by value.
CONTENT_COLUMNS: dict[str, tuple[str, ...]] = {
    "conversations": ("last_message_preview",),
    # A lead's name is PII too; nothing filters on it, so no lookup hash.
    "lead_magnet_leads": ("name",),
    "messages": (
        "body",
        "subject",
        "recipient_email",
        "sender_email",
        "recording_url",
        "transcript",
    ),
    "phone_messages": ("caller_name", "callback_number", "reason", "message_body"),
    "caller_memories": ("summary",),
    "link_clicks": ("ip_address",),
}

#: ``table -> (column, hash_column, kind, not_null)``. ``kind`` selects the
#: hash function so phone normalization matches the ORM exactly.
HASHED_COLUMNS: dict[str, tuple[tuple[str, str, str, bool], ...]] = {
    "conversations": (
        ("workspace_phone", "workspace_phone_hash", "phone", True),
        ("contact_phone", "contact_phone_hash", "phone", True),
    ),
    "global_opt_outs": (("phone_number", "phone_hash", "phone", True),),
    "lead_magnet_leads": (
        ("email", "email_hash", "value", False),
        ("phone_number", "phone_hash", "phone", False),
    ),
    "demo_requests": (("phone_number", "phone_hash", "phone", True),),
    "human_profiles": (
        ("phone_number", "phone_hash", "phone", False),
        ("email", "email_hash", "value", False),
    ),
}

#: Indexes on now-encrypted columns. Dropped on upgrade, restored on downgrade
#: as ``(table, index_name, column, unique)``.
PLAINTEXT_INDEXES: tuple[tuple[str, str, str, bool], ...] = (
    ("conversations", "ix_conversations_contact_phone", "contact_phone", False),
    ("conversations", "ix_conversations_workspace_phone", "workspace_phone", False),
    ("global_opt_outs", "ix_global_opt_outs_phone_number", "phone_number", False),
    ("lead_magnet_leads", "ix_lead_magnet_leads_email", "email", False),
    ("demo_requests", "ix_demo_requests_phone_number", "phone_number", False),
)

#: Original column widths, so ``downgrade()`` restores the schema exactly.
ORIGINAL_TYPES: dict[tuple[str, str], sa.types.TypeEngine[str]] = {
    ("conversations", "workspace_phone"): sa.String(length=20),
    ("conversations", "contact_phone"): sa.String(length=20),
    ("conversations", "last_message_preview"): sa.String(length=255),
    ("messages", "body"): sa.Text(),
    ("messages", "subject"): sa.String(length=500),
    ("messages", "recipient_email"): sa.String(length=255),
    ("messages", "sender_email"): sa.String(length=255),
    ("messages", "recording_url"): sa.Text(),
    ("messages", "transcript"): sa.Text(),
    ("global_opt_outs", "phone_number"): sa.String(length=50),
    ("lead_magnet_leads", "email"): sa.String(length=255),
    ("lead_magnet_leads", "phone_number"): sa.String(length=50),
    ("lead_magnet_leads", "name"): sa.String(length=255),
    ("demo_requests", "phone_number"): sa.String(length=50),
    ("human_profiles", "phone_number"): sa.String(length=50),
    ("human_profiles", "email"): sa.String(length=255),
    ("phone_messages", "caller_name"): sa.String(length=255),
    ("phone_messages", "callback_number"): sa.String(length=50),
    ("phone_messages", "reason"): sa.Text(),
    ("phone_messages", "message_body"): sa.Text(),
    ("caller_memories", "summary"): sa.Text(),
    ("link_clicks", "ip_address"): sa.String(length=64),
}

_FERNET_PREFIX = "gAAAAA"


def _hash_for(kind: str, value: str) -> str:
    return hash_phone(value) if kind == "phone" else hash_value(value)


def _table_exists(bind: sa.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


# --------------------------------------------------------------------------
# Pre-flight
# --------------------------------------------------------------------------


def _assert_no_hash_collisions(bind: sa.Connection) -> None:
    """Fail before mutating data if normalization would violate a new UNIQUE.

    ``uq_conversation_phones`` and ``uq_workspace_opt_out`` move onto hashes of
    *normalized* phone numbers, so rows that differ only by formatting merge.
    Detect that here — while the transaction is still cheap to roll back — and
    tell the operator exactly which rows to reconcile.
    """
    checks = (
        (
            "conversations",
            "uq_conversation_phones",
            ("workspace_id", "workspace_phone", "contact_phone"),
        ),
        ("global_opt_outs", "uq_workspace_opt_out", ("workspace_id", "phone_number")),
    )

    for table, constraint, columns in checks:
        if not _table_exists(bind, table):
            continue

        seen: dict[tuple[str, ...], str] = {}
        collisions: list[str] = []
        select_cols = ", ".join(("id", *columns))
        rows = bind.execute(sa.text(f"SELECT {select_cols} FROM {table}")).mappings()  # noqa: S608

        for row in rows:
            key = tuple(
                str(row[col]) if col == "workspace_id" else _hash_for("phone", str(row[col] or ""))
                for col in columns
            )
            if key in seen:
                collisions.append(f"  row {row['id']} collides with row {seen[key]}")
            else:
                seen[key] = str(row["id"])

        if collisions:
            raise RuntimeError(
                f"Cannot enforce {constraint} on hashed columns: {len(collisions)} row(s) "
                f"in {table!r} differ only by phone formatting and would merge.\n"
                + "\n".join(collisions[:20])
                + "\n\nReconcile these rows (keep the canonical one, repoint or delete "
                "the duplicates), then re-run the migration. No data was modified."
            )


# --------------------------------------------------------------------------
# Data movement
# --------------------------------------------------------------------------


def _encrypt_table(bind: sa.Connection, table: str, columns: Sequence[str]) -> None:
    """Encrypt ``columns`` in place, skipping values already encrypted."""
    fernet = _get_fernet()
    select_cols = ", ".join(("id", *columns))
    rows = bind.execute(sa.text(f"SELECT {select_cols} FROM {table}")).mappings().all()  # noqa: S608

    for row in rows:
        updates: dict[str, str | None] = {}
        for column in columns:
            value = row[column]
            if value is None:
                continue
            text = str(value)
            # Idempotent: a re-run (or a partially-applied prior attempt) must
            # not double-encrypt.
            if text.startswith(_FERNET_PREFIX):
                continue
            updates[column] = fernet.encrypt(text.encode()).decode()

        if updates:
            assignments = ", ".join(f"{col} = :{col}" for col in updates)
            bind.execute(
                sa.text(f"UPDATE {table} SET {assignments} WHERE id = :row_id"),  # noqa: S608
                {**updates, "row_id": row["id"]},
            )


def _encrypt_and_hash(
    bind: sa.Connection, table: str, specs: Sequence[tuple[str, str, str, bool]]
) -> None:
    """Encrypt identifier columns and backfill their deterministic hashes."""
    fernet = _get_fernet()
    columns = [spec[0] for spec in specs]
    select_cols = ", ".join(("id", *columns))
    rows = bind.execute(sa.text(f"SELECT {select_cols} FROM {table}")).mappings().all()  # noqa: S608

    for row in rows:
        updates: dict[str, str | None] = {}
        for column, hash_column, kind, _not_null in specs:
            value = row[column]
            if value is None:
                updates[hash_column] = None
                continue
            text = str(value)
            if text.startswith(_FERNET_PREFIX):
                # Value already encrypted by a prior partial run; its plaintext
                # is unavailable here, so recover the hash by decrypting.
                text = fernet.decrypt(text.encode()).decode()
            else:
                updates[column] = fernet.encrypt(text.encode()).decode()
            updates[hash_column] = _hash_for(kind, text)

        if updates:
            assignments = ", ".join(f"{col} = :{col}" for col in updates)
            bind.execute(
                sa.text(f"UPDATE {table} SET {assignments} WHERE id = :row_id"),  # noqa: S608
                {**updates, "row_id": row["id"]},
            )


def _decrypt_table(bind: sa.Connection, table: str, columns: Sequence[str]) -> None:
    """Decrypt ``columns`` back to plaintext for ``downgrade()``."""
    fernet = _get_fernet()
    select_cols = ", ".join(("id", *columns))
    rows = bind.execute(sa.text(f"SELECT {select_cols} FROM {table}")).mappings().all()  # noqa: S608

    for row in rows:
        updates: dict[str, str] = {}
        for column in columns:
            value = row[column]
            if value is None:
                continue
            text = str(value)
            if not text.startswith(_FERNET_PREFIX):
                continue
            updates[column] = fernet.decrypt(text.encode()).decode()

        if updates:
            assignments = ", ".join(f"{col} = :{col}" for col in updates)
            bind.execute(
                sa.text(f"UPDATE {table} SET {assignments} WHERE id = :row_id"),  # noqa: S608
                {**updates, "row_id": row["id"]},
            )


# --------------------------------------------------------------------------
# Upgrade / downgrade
# --------------------------------------------------------------------------


# The step-by-step ordering below is the point of this migration, so both
# functions read as a linear checklist rather than being split into helpers
# that would obscure the sequence.
def upgrade() -> None:  # noqa: PLR0912
    bind = op.get_bind()

    # 1. Fail fast, before touching a single row.
    _assert_no_hash_collisions(bind)

    # 2. Widen every target column to TEXT. Ciphertext is far longer than the
    #    plaintext it replaces (a 12-char phone becomes ~120 chars), so this
    #    must happen before any encryption.
    for (table, column), _original in ORIGINAL_TYPES.items():
        if _table_exists(bind, table):
            op.alter_column(table, column, type_=sa.Text(), existing_nullable=None)

    # 3. Drop indexes that point at soon-to-be-ciphertext columns.
    for table, index_name, _column, _unique in PLAINTEXT_INDEXES:
        if _table_exists(bind, table):
            op.execute(f'DROP INDEX IF EXISTS "{index_name}"')

    # 4. Drop the composite demo-request index so its phone column can move to
    #    the hash (it backs the rate-limit window scan).
    if _table_exists(bind, "demo_requests"):
        op.execute('DROP INDEX IF EXISTS "ix_demo_requests_phone_created_at"')

    # 5. Drop the two uniqueness constraints before their columns become
    #    non-deterministic ciphertext.
    if _table_exists(bind, "conversations"):
        op.execute('ALTER TABLE conversations DROP CONSTRAINT IF EXISTS "uq_conversation_phones"')
    if _table_exists(bind, "global_opt_outs"):
        op.execute('ALTER TABLE global_opt_outs DROP CONSTRAINT IF EXISTS "uq_workspace_opt_out"')

    # 6. Add hash columns (nullable for now — backfill populates them).
    for table, specs in HASHED_COLUMNS.items():
        if not _table_exists(bind, table):
            continue
        for _column, hash_column, _kind, _not_null in specs:
            op.add_column(table, sa.Column(hash_column, sa.Text(), nullable=True))

    # 7. Encrypt data and backfill hashes.
    for table, columns in CONTENT_COLUMNS.items():
        if _table_exists(bind, table):
            _encrypt_table(bind, table, columns)

    for table, specs in HASHED_COLUMNS.items():
        if _table_exists(bind, table):
            _encrypt_and_hash(bind, table, specs)

    # 8. Enforce NOT NULL where the ORM declares it, now that data exists.
    for table, specs in HASHED_COLUMNS.items():
        if not _table_exists(bind, table):
            continue
        for _column, hash_column, _kind, not_null in specs:
            if not_null:
                op.alter_column(table, hash_column, nullable=False)

    # 9. Index the hashes and restore uniqueness on them.
    for table, specs in HASHED_COLUMNS.items():
        if not _table_exists(bind, table):
            continue
        for _column, hash_column, _kind, _not_null in specs:
            op.create_index(f"ix_{table}_{hash_column}", table, [hash_column], unique=False)

    if _table_exists(bind, "conversations"):
        op.create_unique_constraint(
            "uq_conversation_phones",
            "conversations",
            ["workspace_id", "workspace_phone_hash", "contact_phone_hash"],
        )
    if _table_exists(bind, "global_opt_outs"):
        op.create_unique_constraint(
            "uq_workspace_opt_out", "global_opt_outs", ["workspace_id", "phone_hash"]
        )
    if _table_exists(bind, "demo_requests"):
        op.create_index(
            "ix_demo_requests_phone_created_at",
            "demo_requests",
            ["phone_hash", "created_at"],
            unique=False,
        )


def downgrade() -> None:  # noqa: PLR0912
    bind = op.get_bind()

    # 1. Drop hash-based uniqueness/indexes first.
    if _table_exists(bind, "conversations"):
        op.execute('ALTER TABLE conversations DROP CONSTRAINT IF EXISTS "uq_conversation_phones"')
    if _table_exists(bind, "global_opt_outs"):
        op.execute('ALTER TABLE global_opt_outs DROP CONSTRAINT IF EXISTS "uq_workspace_opt_out"')
    if _table_exists(bind, "demo_requests"):
        op.execute('DROP INDEX IF EXISTS "ix_demo_requests_phone_created_at"')

    for table, specs in HASHED_COLUMNS.items():
        if not _table_exists(bind, table):
            continue
        for _column, hash_column, _kind, _not_null in specs:
            op.execute(f'DROP INDEX IF EXISTS "ix_{table}_{hash_column}"')

    # 2. Decrypt everything back to plaintext.
    for table, columns in CONTENT_COLUMNS.items():
        if _table_exists(bind, table):
            _decrypt_table(bind, table, columns)

    for table, specs in HASHED_COLUMNS.items():
        if _table_exists(bind, table):
            _decrypt_table(bind, table, [spec[0] for spec in specs])

    # 3. Drop the hash columns.
    for table, specs in HASHED_COLUMNS.items():
        if not _table_exists(bind, table):
            continue
        for _column, hash_column, _kind, _not_null in specs:
            op.drop_column(table, hash_column)

    # 4. Restore original column widths.
    for (table, column), original in ORIGINAL_TYPES.items():
        if _table_exists(bind, table):
            op.alter_column(
                table,
                column,
                type_=original,
                existing_nullable=None,
                postgresql_using=f"{column}::text",
            )

    # 5. Restore the plaintext indexes and constraints.
    for table, index_name, column, unique in PLAINTEXT_INDEXES:
        if _table_exists(bind, table):
            op.create_index(index_name, table, [column], unique=unique)

    if _table_exists(bind, "conversations"):
        op.create_unique_constraint(
            "uq_conversation_phones",
            "conversations",
            ["workspace_id", "workspace_phone", "contact_phone"],
        )
    if _table_exists(bind, "global_opt_outs"):
        op.create_unique_constraint(
            "uq_workspace_opt_out", "global_opt_outs", ["workspace_id", "phone_number"]
        )
    if _table_exists(bind, "demo_requests"):
        op.create_index(
            "ix_demo_requests_phone_created_at",
            "demo_requests",
            ["phone_number", "created_at"],
            unique=False,
        )
