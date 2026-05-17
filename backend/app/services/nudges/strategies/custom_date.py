"""Custom date nudge strategy."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    maybe_create_date_nudge,
)


class CustomDateNudgeStrategy(NudgeStrategy):
    """Create nudges for any user-defined ``custom`` important dates."""

    nudge_type = "custom"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        count = 0
        for contact in context.date_contacts:
            dates = contact.important_dates
            if not dates:
                continue
            custom_dates: list[dict[str, str]] = dates.get("custom", [])
            for custom in custom_dates:
                label = custom.get("label", "Event")
                date_str = custom.get("date")
                if date_str:
                    count += await maybe_create_date_nudge(
                        db, context, contact, "custom", date_str, label=label
                    )
        return count
