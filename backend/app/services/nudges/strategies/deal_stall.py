"""Deal-milestone (stall + overdue) nudge strategy."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.human_nudge import HumanNudge
from app.models.opportunity import Opportunity
from app.models.pipeline import PipelineStage
from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    dedup_exists,
    load_contact,
)

DEAL_STALL_DAYS = 7
HIGH_VALUE_THRESHOLD = 50000


class DealStallNudgeStrategy(NudgeStrategy):
    """Create nudges for deals stuck in one stage or past their expected close date."""

    nudge_type = "deal_milestone"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        count = await self._generate_stalls(db, context)
        count += await self._generate_overdue(db, context)
        return count

    async def _generate_stalls(self, db: AsyncSession, context: NudgeContext) -> int:
        now = context.now
        cutoff = now - timedelta(days=DEAL_STALL_DAYS)
        year = now.year
        week_number = now.isocalendar()[1]

        result = await db.execute(
            select(Opportunity).where(
                Opportunity.workspace_id == context.workspace_id,
                Opportunity.status == "open",
                Opportunity.stage_changed_at.isnot(None),
                Opportunity.stage_changed_at < cutoff,
            )
        )
        opportunities = result.scalars().all()

        count = 0
        for opp in opportunities:
            if opp.primary_contact_id is None:
                continue

            dedup_key = f"{opp.id}:stalled:{year}:{week_number}"
            if await dedup_exists(db, dedup_key):
                continue

            contact = await load_contact(db, opp.primary_contact_id)
            if contact is None:
                continue

            stage_name = "unknown stage"
            if opp.stage_id is not None:
                stage_result = await db.execute(
                    select(PipelineStage.name).where(PipelineStage.id == opp.stage_id).limit(1)
                )
                stage_name = stage_result.scalar_one_or_none() or "unknown stage"

            name = contact.full_name
            assert opp.stage_changed_at is not None
            days_stalled = (now - opp.stage_changed_at).days
            amount = float(opp.amount) if opp.amount is not None else 0
            priority = "high" if amount > HIGH_VALUE_THRESHOLD else "medium"

            nudge = HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=opp.primary_contact_id,
                nudge_type="deal_milestone",
                title=f"Move {name}'s deal forward",
                message=(
                    f"{name}'s {opp.name} (${amount:,.0f}) has been in "
                    f"{stage_name} for {days_stalled} days."
                ),
                suggested_action="call",
                priority=priority,
                due_date=now,
                source_date_field=None,
                status="pending",
                dedup_key=dedup_key,
            )
            db.add(nudge)
            count += 1

        return count

    async def _generate_overdue(self, db: AsyncSession, context: NudgeContext) -> int:
        now = context.now
        today = now.date()
        year = now.year
        month = now.month

        result = await db.execute(
            select(Opportunity).where(
                Opportunity.workspace_id == context.workspace_id,
                Opportunity.status == "open",
                Opportunity.expected_close_date.isnot(None),
                Opportunity.expected_close_date < today,
            )
        )
        opportunities = result.scalars().all()

        count = 0
        for opp in opportunities:
            if opp.primary_contact_id is None:
                continue

            dedup_key = f"{opp.id}:overdue:{year}:{month}"
            if await dedup_exists(db, dedup_key):
                continue

            contact = await load_contact(db, opp.primary_contact_id)
            if contact is None:
                continue

            name = contact.full_name
            assert opp.expected_close_date is not None
            days_overdue = (today - opp.expected_close_date).days

            nudge = HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=opp.primary_contact_id,
                nudge_type="deal_milestone",
                title=f"\u26a0\ufe0f {name}'s deal is past due",
                message=f"{opp.name} was expected to close {days_overdue} days ago.",
                suggested_action="call",
                priority="high",
                due_date=now,
                source_date_field=None,
                status="pending",
                dedup_key=dedup_key,
            )
            db.add(nudge)
            count += 1

        return count
