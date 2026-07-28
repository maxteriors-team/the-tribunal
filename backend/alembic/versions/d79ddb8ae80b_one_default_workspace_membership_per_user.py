"""Repair duplicate default memberships and enforce one default per user.

Revision ID: d79ddb8ae80b
Revises: c0642b9bfdce
Create Date: 2026-07-28 10:35:00.000000

``POST /api/v1/workspaces`` flagged its new membership ``is_default=True``
without clearing the caller's previous default (unlike
``POST /workspaces/{id}/set-default``, which does). Anyone who ever created a
second workspace therefore ended up with two default rows, and the resolvers
behind ``/api/v1/onboarding/*`` and ``/api/v1/billing/*`` \u2014 which asked for "the"
default with an unbounded ``scalar_one_or_none()`` \u2014 raised
``MultipleResultsFound`` and returned 500 on every one of those routes.

Repair keeps the user's **earliest** membership as the default and clears the
rest, matching the tie-break every resolver now uses (``created_at``, then
``id``), so resolution is identical before and after this runs. The partial
unique index then makes the invariant the code has always assumed a property the
database enforces.

Note the index is intentionally partial (``WHERE is_default``): a user may hold
any number of non-default memberships. Partial unique indexes cannot be
DEFERRABLE in Postgres, so every writer must clear before promoting \u2014 that
ordering lives in
:func:`app.services.workspaces.membership.set_default_membership`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d79ddb8ae80b"
down_revision: str | None = "c0642b9bfdce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_workspace_membership_default_per_user"


def upgrade() -> None:
    # Demote every default except the earliest one per user.
    op.execute(
        """
        UPDATE workspace_memberships m
           SET is_default = false
         WHERE m.is_default
           AND m.id <> (
                 SELECT keep.id
                   FROM workspace_memberships keep
                  WHERE keep.user_id = m.user_id
                    AND keep.is_default
                  ORDER BY keep.created_at ASC, keep.id ASC
                  LIMIT 1
               )
        """
    )

    op.create_index(
        INDEX_NAME,
        "workspace_memberships",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    # Only the constraint is reversible; demoted rows are not restored (the
    # duplicate-default state this repaired was corruption, not user intent).
    op.drop_index(INDEX_NAME, table_name="workspace_memberships")
