"""Operator-level nudge: fresh ad-library contacts awaiting an outbound batch."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import CampaignContact
from app.models.contact import Contact
from app.models.human_nudge import HumanNudge
from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    dedup_exists,
)

# Don't nag the operator over a trickle; wait for a meaningful batch.
MIN_BATCH_SIZE = 5


class OutboundBatchReadyNudgeStrategy(NudgeStrategy):
    """Nudge the operator when un-campaigned ad-library contacts pile up.

    Workspace-level (``contact_id=None``): the nudge is about the state of
    the outbound machine, not a single relationship. Deduped per workspace
    per day.
    """

    nudge_type = "outbound_batch_ready"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        dedup_key = f"{context.workspace_id}:outbound_batch_ready:{context.today.isoformat()}"
        if await dedup_exists(db, dedup_key):
            return 0

        enrolled = select(CampaignContact.contact_id)
        result = await db.execute(
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.workspace_id == context.workspace_id,
                Contact.source == "ad_library",
                Contact.id.notin_(enrolled),
            )
        )
        count = result.scalar() or 0
        if count < MIN_BATCH_SIZE:
            return 0

        db.add(
            HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=None,
                nudge_type="outbound_batch_ready",
                title=f"\U0001f4e6 {count} fresh advertisers ready",
                message=(
                    f"\U0001f4e6 {count} ad-library contacts have never been enrolled in a "
                    "campaign. Review the batch and launch outreach."
                ),
                suggested_action=None,
                priority="high",
                due_date=context.now,
                source_date_field=None,
                status="pending",
                dedup_key=dedup_key,
            )
        )
        return 1
