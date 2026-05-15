"""Set Jess agent to Grok provider with Eve voice in PRESTYJ workspace.

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-02-08

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6g7h8i9j0"
down_revision: str | None = "d4e5f6g7h8i9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JESS_AGENT_ID = "5bba3103-f3e0-4eb8-bec0-5423bf4051d4"


def upgrade() -> None:
    op.execute(
        f"UPDATE agents SET voice_provider = 'grok', voice_id = 'eve' "
        f"WHERE id = '{JESS_AGENT_ID}'"
    )


def downgrade() -> None:
    """Downgrade not supported.

    The upgrade overwrites ``voice_provider`` and ``voice_id`` on the Jess
    agent row without capturing the prior values. There is no record of what
    those columns held before this migration ran, so a faithful reversal is
    impossible. Restoring stale defaults could silently corrupt production
    configuration, so we fail loudly instead.
    """
    raise NotImplementedError(
        "Downgrade not supported: data mutation is one-way"
    )
