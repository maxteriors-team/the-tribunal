"""Change conversations.contact_id FK to ON DELETE CASCADE.

The ``Contact.conversations`` relationship declares
``cascade="all, delete-orphan"`` in the ORM, meaning deleting a contact
should also delete its conversations. The underlying FK constraint
``conversations_contact_id_fkey`` was created with ``ON DELETE SET NULL``,
so any raw SQL delete (alembic data migrations, manual cleanup,
bulk-delete statements that bypass the ORM session) would orphan the
conversation rows with ``contact_id = NULL`` instead of removing them.

Aligning the DB-level FK with the ORM cascade keeps tenant data isolation
guarantees intact: when a contact is purged, every conversation thread
tied to that contact is purged with it, regardless of which code path
issued the delete.

``contact_id`` remains nullable — conversations can still be created
without a known contact (e.g. inbound SMS before contact resolution) —
but once a contact is linked, deletion cascades.

Revision ID: 9a01178f7789
Revises: e0f1a2b3c4d5
Create Date: 2026-05-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a01178f7789"
down_revision: str | None = "e0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Constraint name follows the project naming convention defined in
# ``app/db/base.py``: ``fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s``.
_FK_NAME = "fk_conversations_contact_id_contacts"


def _existing_contact_fk_name() -> str | None:
    result = op.get_bind().execute(
        sa.text(
            """
            SELECT con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            JOIN pg_attribute att
              ON att.attrelid = rel.oid
             AND att.attnum = ANY (con.conkey)
            JOIN pg_class ref_rel ON ref_rel.oid = con.confrelid
            WHERE con.contype = 'f'
              AND nsp.nspname = current_schema()
              AND rel.relname = 'conversations'
              AND att.attname = 'contact_id'
              AND ref_rel.relname = 'contacts'
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    return str(result) if result is not None else None


def _replace_contact_fk(*, ondelete: str) -> None:
    existing_fk_name = _existing_contact_fk_name()
    if existing_fk_name is not None:
        op.drop_constraint(existing_fk_name, "conversations", type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        "conversations",
        "contacts",
        ["contact_id"],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    _replace_contact_fk(ondelete="CASCADE")


def downgrade() -> None:
    _replace_contact_fk(ondelete="SET NULL")
