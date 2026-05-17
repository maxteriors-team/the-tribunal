"""Anniversary nudge strategy."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    maybe_create_date_nudge,
)


class AnniversaryNudgeStrategy(NudgeStrategy):
    """Create nudges for contacts whose anniversary falls within the lookahead window."""

    nudge_type = "anniversary"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        count = 0
        for contact in context.date_contacts:
            dates = contact.important_dates
            if not dates:
                continue
            anniversary_str = dates.get("anniversary")
            if anniversary_str:
                count += await maybe_create_date_nudge(
                    db, context, contact, "anniversary", anniversary_str
                )
        return count
