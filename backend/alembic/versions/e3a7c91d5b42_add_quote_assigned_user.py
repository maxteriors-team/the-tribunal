"""add quote sales owner

Revision ID: e3a7c91d5b42
Revises: b7e4c9a1d2f3
Create Date: 2026-08-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3a7c91d5b42"
down_revision: str | Sequence[str] | None = "b7e4c9a1d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_quotes_assigned_user_id"


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column(
            "assigned_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(_INDEX_NAME, "quotes", ["assigned_user_id"], unique=False)

    # Prefer the linked deal's owner, then the quote creator. Both candidates
    # must belong to the quote's workspace; invalid historical links stay null.
    op.execute(
        sa.text(
            """
            UPDATE quotes AS q
            SET assigned_user_id = COALESCE(
                (
                    SELECT o.assigned_user_id
                    FROM opportunities AS o
                    WHERE o.id = q.opportunity_id
                      AND o.workspace_id = q.workspace_id
                      AND o.assigned_user_id IS NOT NULL
                      AND EXISTS (
                          SELECT 1
                          FROM workspace_memberships AS m
                          WHERE m.workspace_id = q.workspace_id
                            AND m.user_id = o.assigned_user_id
                      )
                ),
                CASE
                    WHEN q.created_by_id IS NOT NULL
                     AND EXISTS (
                         SELECT 1
                         FROM workspace_memberships AS m
                         WHERE m.workspace_id = q.workspace_id
                           AND m.user_id = q.created_by_id
                     )
                    THEN q.created_by_id
                END
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="quotes")
    op.drop_column("quotes", "assigned_user_id")
