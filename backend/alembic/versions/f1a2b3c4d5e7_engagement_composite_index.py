"""Replace standalone ix_contacts_last_engaged_at with composite (workspace_id, last_engaged_at).

Contact list queries always filter by workspace_id first, so a standalone
index on last_engaged_at can't be used for the common sort-by-recency path.

Revision ID: f1a2b3c4d5e7
Revises: ea2f3b4c5d6e7
Create Date: 2026-04-15
"""

from alembic import op

revision = "f1a2b3c4d5e7"
down_revision = "ea2f3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_contacts_last_engaged_at", table_name="contacts")
    op.create_index(
        "ix_contacts_workspace_last_engaged",
        "contacts",
        ["workspace_id", "last_engaged_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_contacts_workspace_last_engaged", table_name="contacts")
    op.create_index(
        "ix_contacts_last_engaged_at",
        "contacts",
        ["last_engaged_at"],
        unique=False,
    )
