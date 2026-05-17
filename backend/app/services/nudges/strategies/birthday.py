"""Birthday nudge strategy."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    maybe_create_date_nudge,
)


class BirthdayNudgeStrategy(NudgeStrategy):
    """Create nudges for contacts whose birthday falls within the lookahead window."""

    nudge_type = "birthday"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        count = 0
        for contact in context.date_contacts:
            dates = contact.important_dates
            if not dates:
                continue
            birthday_str = dates.get("birthday")
            if birthday_str:
                count += await maybe_create_date_nudge(
                    db, context, contact, "birthday", birthday_str
                )
        return count
