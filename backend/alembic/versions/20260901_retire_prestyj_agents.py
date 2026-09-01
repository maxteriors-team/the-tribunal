"""retire auto-seeded Prestyj cold-lead responder agents

Revision ID: 20260901_retire_prestyj
Revises: cc285c87ccd1
Create Date: 2026-09-01

Every workspace with no agent used to get a "Prestyj Cold-Lead Responder"
auto-seeded into it -- a different company's script (Batch Video Ads, a $497
starter offer) answering the operator's real customers. The seeding is gone in
this release, but the rows it already created are still there and still
answering, so they have to be retired too or nothing changes for live traffic.

Scoped deliberately narrowly: only rows whose ``system_prompt`` is *byte-for-byte*
the seeded template. An operator who edited the prompt owns that agent now, and
it is left completely alone -- this fails in the safe direction, leaving a row
behind rather than retiring one somebody customised.

Soft delete, not DELETE: agents are referenced by calls, conversations,
appointments, knowledge documents and training examples, several with
``ON DELETE CASCADE``. Removing the row would take that history with it.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_retire_prestyj"
down_revision: str | None = "cc285c87ccd1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A fixed, recognisable marker so downgrade reverses exactly the rows this
# migration touched and nothing an operator deleted themselves. asyncpg binds
# timestamptz parameters as real datetimes, not strings.
RETIRED_AT = datetime(2026, 9, 1, tzinfo=UTC)

PROMPT_FIRST_LINE = "You are the Prestyj cold-lead responder for Batch Video Ads."


def upgrade() -> None:
    # Match on the seeded prompt's opening line rather than the agent name:
    # renaming the agent is cosmetic, but that prompt is what actually talks to
    # customers. LIKE with a literal prefix -- no wildcards from user data.
    result = op.get_bind().execute(
        sa.text(
            """
            UPDATE agents
               SET deleted_at = :retired_at,
                   is_active = false
             WHERE deleted_at IS NULL
               AND system_prompt LIKE :prompt_prefix
            """
        ),
        {"retired_at": RETIRED_AT, "prompt_prefix": f"{PROMPT_FIRST_LINE}%"},
    )
    print(f"retired {result.rowcount} auto-seeded Prestyj agent(s)")


def downgrade() -> None:
    # Restores only what upgrade() retired: the marker timestamp plus the
    # template prompt. Agents the operator deleted by hand carry a different
    # timestamp and stay deleted.
    #
    # is_active is deliberately NOT restored. This migration cannot know whether
    # a given agent was active before it ran, and guessing "true" would put a
    # foreign sales script back on live inbound traffic. Undeleting is enough to
    # make the row visible again; re-activating is the operator's call.
    op.get_bind().execute(
        sa.text(
            """
            UPDATE agents
               SET deleted_at = NULL
             WHERE deleted_at = :retired_at
               AND system_prompt LIKE :prompt_prefix
            """
        ),
        {"retired_at": RETIRED_AT, "prompt_prefix": f"{PROMPT_FIRST_LINE}%"},
    )
