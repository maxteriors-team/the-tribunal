"""Post-meeting follow-up nudge strategy."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.conversation import Conversation
from app.models.human_nudge import HumanNudge
from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    dedup_exists,
    load_contact,
)


class FollowUpNudgeStrategy(NudgeStrategy):
    """Create nudges to follow up with contacts after completed meetings."""

    nudge_type = "follow_up"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        now = context.now
        window_start = now - timedelta(days=7)
        window_end = now - timedelta(days=2)

        result = await db.execute(
            select(Appointment).where(
                Appointment.workspace_id == context.workspace_id,
                Appointment.status == "completed",
                Appointment.scheduled_at >= window_start,
                Appointment.scheduled_at <= window_end,
            )
        )
        appointments = result.scalars().all()

        count = 0
        for appt in appointments:
            contact_id = appt.contact_id
            dedup_key = f"{contact_id}:post_meeting:{appt.id}"

            if await dedup_exists(db, dedup_key):
                continue

            conv_result = await db.execute(
                select(Conversation)
                .where(
                    Conversation.workspace_id == context.workspace_id,
                    Conversation.contact_id == contact_id,
                    Conversation.last_message_at > appt.scheduled_at,
                    Conversation.last_message_direction == "outbound",
                )
                .limit(1)
            )
            if conv_result.scalar_one_or_none() is not None:
                continue

            contact = await load_contact(db, contact_id)
            if contact is None:
                continue

            name = contact.full_name
            days_since = (now - appt.scheduled_at).days
            priority = "high" if days_since <= 4 else "medium"

            nudge = HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=contact_id,
                nudge_type="follow_up",
                title=f"Follow up with {name} after your meeting",
                message=(
                    f"You met with {name} {days_since} days ago. "
                    f"A quick check-in can solidify the relationship."
                ),
                suggested_action="text",
                priority=priority,
                due_date=now,
                source_date_field=None,
                status="pending",
                dedup_key=dedup_key,
            )
            db.add(nudge)
            count += 1

        return count
