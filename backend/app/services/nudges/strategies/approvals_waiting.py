"""Operator-level nudge: pending approvals are going stale."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.human_nudge import HumanNudge
from app.models.pending_action import PendingAction
from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    dedup_exists,
)

# Only nag once approvals have sat unreviewed for this long.
STALE_AFTER_HOURS = 2


class ApprovalsWaitingNudgeStrategy(NudgeStrategy):
    """Nudge the operator when pending approvals are older than 2 hours.

    Workspace-level (``contact_id=None``), deduped per workspace per day.
    """

    nudge_type = "approvals_waiting"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        dedup_key = f"{context.workspace_id}:approvals_waiting:{context.today.isoformat()}"
        if await dedup_exists(db, dedup_key):
            return 0

        stale_before = context.now - timedelta(hours=STALE_AFTER_HOURS)
        result = await db.execute(
            select(func.count())
            .select_from(PendingAction)
            .where(
                PendingAction.workspace_id == context.workspace_id,
                PendingAction.status == "pending",
                PendingAction.created_at <= stale_before,
            )
        )
        count = result.scalar() or 0
        if count == 0:
            return 0

        plural = "s" if count != 1 else ""
        db.add(
            HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=None,
                nudge_type="approvals_waiting",
                title=f"\u23f3 {count} approval{plural} waiting",
                message=(
                    f"\u23f3 {count} pending action{plural} have been waiting more than "
                    f"{STALE_AFTER_HOURS} hours. Approve or reject them before they expire."
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
