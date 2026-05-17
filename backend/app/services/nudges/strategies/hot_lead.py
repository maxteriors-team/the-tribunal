"""Hot lead nudge strategy."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.human_nudge import HumanNudge
from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    dedup_exists,
)


class HotLeadNudgeStrategy(NudgeStrategy):
    """Create nudges for contacts flagged as high-interest leads."""

    nudge_type = "hot_lead"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        now = context.now
        year = now.year
        quarter = (now.month - 1) // 3 + 1

        result = await db.execute(
            select(Contact).where(
                Contact.workspace_id == context.workspace_id,
                Contact.qualification_signals.isnot(None),
                Contact.status.notin_(["converted", "lost"]),
            )
        )
        contacts = result.scalars().all()

        count = 0
        for contact in contacts:
            signals = contact.qualification_signals
            if not isinstance(signals, dict):
                continue
            if signals.get("interest_level") != "high":
                continue

            dedup_key = f"{contact.id}:hot_lead:{year}:{quarter}"
            if await dedup_exists(db, dedup_key):
                continue

            name = contact.full_name

            nudge = HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=contact.id,
                nudge_type="hot_lead",
                title=f"\U0001f525 {name} is a hot lead",
                message=(
                    f"{name} shows high interest. "
                    f"Strike while the iron's hot \u2014 book a meeting."
                ),
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
