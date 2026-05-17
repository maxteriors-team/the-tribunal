"""Unresponsive lead nudge strategy."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.human_nudge import HumanNudge
from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    dedup_exists,
)


class UnresponsiveNudgeStrategy(NudgeStrategy):
    """Create nudges for new/contacted leads who haven't replied to outbound messages."""

    nudge_type = "unresponsive"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        now = context.now
        cutoff = now - timedelta(days=5)
        year = now.year
        month = now.month

        result = await db.execute(
            select(Conversation).where(
                Conversation.workspace_id == context.workspace_id,
                Conversation.last_message_at.isnot(None),
                Conversation.last_message_at < cutoff,
                Conversation.last_message_direction == "outbound",
                Conversation.contact_id.isnot(None),
            )
        )
        conversations = result.scalars().all()

        count = 0
        seen_contacts: set[int] = set()

        for conv in conversations:
            contact_id = conv.contact_id
            if contact_id is None or contact_id in seen_contacts:
                continue

            contact_result = await db.execute(
                select(Contact)
                .where(
                    Contact.id == contact_id,
                    Contact.status.in_(["new", "contacted"]),
                )
                .limit(1)
            )
            contact = contact_result.scalar_one_or_none()
            if contact is None:
                continue

            seen_contacts.add(contact_id)
            dedup_key = f"{contact_id}:unresponsive:{year}:{month}"

            if await dedup_exists(db, dedup_key):
                continue

            name = contact.full_name
            assert conv.last_message_at is not None
            days_silent = (now - conv.last_message_at).days

            nudge = HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=contact_id,
                nudge_type="unresponsive",
                title=f"Re-engage {name}",
                message=(
                    f"{name} hasn't replied in {days_silent} days. Try a different angle or offer."
                ),
                suggested_action="text",
                priority="medium",
                due_date=now,
                source_date_field=None,
                status="pending",
                dedup_key=dedup_key,
            )
            db.add(nudge)
            count += 1

        return count
