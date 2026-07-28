"""Add workspaces.onboarding_completed_at (explicit onboarding signal).

Revision ID: c0642b9bfdce
Revises: 1dce03676e16
Create Date: 2026-07-28 10:20:00.000000

Setup state used to be inferred from "does this workspace have zero AI agents?",
which is false: ``POST /api/v1/workspaces`` seeds a template agent at creation
time, so a UI-created workspace reported "configured" seconds after birth and
could never reach the onboarding wizard, while registration-created workspaces
(no seeded agent) always reported "needs setup". This column replaces that
inference with an explicit stamp written when the operator actually finishes the
wizard.

Backfill policy for pre-existing rows: NULL ("never onboarded") by default, but
any workspace with real operator activity — contacts, campaigns, conversations,
appointments, phone numbers, or connected integrations — is stamped as completed
so established customers are not re-prompted into the wizard. Seeded rows (the
default agent and default pipeline) are deliberately NOT treated as activity;
they are exactly the rows that caused the bug. The stamp uses the workspace's
own ``created_at`` because the real completion time is unknowable in retrospect;
it only ever has to read as "before now".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0642b9bfdce"
down_revision: str | None = "1dce03676e16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables whose mere existence proves an operator did real work in the workspace.
_ACTIVITY_TABLES = (
    "contacts",
    "campaigns",
    "conversations",
    "appointments",
    "phone_numbers",
    "workspace_integrations",
)


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    activity_predicate = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} t WHERE t.workspace_id = w.id)"
        for table in _ACTIVITY_TABLES
    )
    op.execute(
        f"""
        UPDATE workspaces w
           SET onboarding_completed_at = w.created_at
         WHERE w.onboarding_completed_at IS NULL
           AND ({activity_predicate})
        """  # noqa: S608 - table names are a fixed in-module tuple, not user input
    )


def downgrade() -> None:
    op.drop_column("workspaces", "onboarding_completed_at")
