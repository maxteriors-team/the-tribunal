"""Cooling-relationship nudge strategy."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.human_nudge import HumanNudge
from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    build_nudge_message,
    dedup_exists,
    load_contact,
)


class CoolingNudgeStrategy(NudgeStrategy):
    """Create nudges for contacts whose conversations have gone silent."""

    nudge_type = "cooling"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        now = context.now
        cutoff = now - timedelta(days=context.cooling_days)
        year = now.year
        month = now.month

        result = await db.execute(
            select(Conversation).where(
                Conversation.workspace_id == context.workspace_id,
                Conversation.last_message_at.isnot(None),
                Conversation.last_message_at < cutoff,
                Conversation.status == "active",
                Conversation.contact_id.isnot(None),
            )
        )
        cold_conversations = result.scalars().all()

        count = 0
        seen_contacts: set[int] = set()

        for conv in cold_conversations:
            contact_id = conv.contact_id
            if contact_id is None or contact_id in seen_contacts:
                continue
            seen_contacts.add(contact_id)

            dedup_key = f"{contact_id}:cooling:{year}:{month}"
            if await dedup_exists(db, dedup_key):
                continue

            contact = await load_contact(db, contact_id)
            if contact is None:
                continue

            assert conv.last_message_at is not None  # guarded by isnot(None) filter
            days_silent: int = (now - conv.last_message_at).days

            title, message, suggested_action = build_nudge_message(
                contact,
                "cooling",
                days_until=days_silent,
            )

            nudge = HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=contact_id,
                nudge_type="cooling",
                title=title,
                message=message,
                suggested_action=suggested_action,
                priority="low",
                due_date=now,
                source_date_field=None,
                status="pending",
                dedup_key=dedup_key,
            )
            db.add(nudge)
            count += 1

        return count
