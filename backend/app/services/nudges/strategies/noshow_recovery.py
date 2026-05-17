"""No-show recovery nudge strategy."""

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


class NoShowRecoveryNudgeStrategy(NudgeStrategy):
    """Create nudges for contacts who recently missed an appointment."""

    nudge_type = "noshow_recovery"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        now = context.now
        window_start = now - timedelta(days=3)
        window_end = now - timedelta(days=1)

        result = await db.execute(
            select(Appointment).where(
                Appointment.workspace_id == context.workspace_id,
                Appointment.status == "no_show",
                Appointment.scheduled_at >= window_start,
                Appointment.scheduled_at <= window_end,
            )
        )
        appointments = result.scalars().all()

        count = 0
        for appt in appointments:
            contact_id = appt.contact_id
            dedup_key = f"{contact_id}:noshow_recovery:{appt.id}"

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

            nudge = HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=contact_id,
                nudge_type="noshow_recovery",
                title=f"Recover no-show with {name}",
                message=(
                    f"{name} missed their appointment {days_since} days ago. "
                    f"A friendly reschedule text works."
                ),
                suggested_action="text",
                priority="high",
                due_date=now,
                source_date_field=None,
                status="pending",
                dedup_key=dedup_key,
            )
            db.add(nudge)
            count += 1

        return count
