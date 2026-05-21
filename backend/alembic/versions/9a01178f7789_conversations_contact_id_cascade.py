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

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a01178f7789"
down_revision: str | None = "e0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Constraint name follows the project naming convention defined in
# ``app/db/base.py``: ``fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s``.
_FK_NAME = "fk_conversations_contact_id_contacts"


def upgrade() -> None:
    op.drop_constraint(_FK_NAME, "conversations", type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        "conversations",
        "contacts",
        ["contact_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, "conversations", type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        "conversations",
        "contacts",
        ["contact_id"],
        ["id"],
        ondelete="SET NULL",
    )
