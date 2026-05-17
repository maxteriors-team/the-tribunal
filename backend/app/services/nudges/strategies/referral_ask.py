"""Referral-ask nudge strategy."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.human_nudge import HumanNudge
from app.models.opportunity import Opportunity
from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    dedup_exists,
    load_contact,
)


class ReferralAskNudgeStrategy(NudgeStrategy):
    """Create nudges prompting referral requests from happy clients."""

    nudge_type = "referral_ask"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        now = context.now
        year = now.year
        quarter = (now.month - 1) // 3 + 1
        window_start = now - timedelta(days=30)
        window_end = now - timedelta(days=14)

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
        seen_contacts: set[int] = set()

        for appt in appointments:
            contact_id = appt.contact_id
            if contact_id in seen_contacts:
                continue

            dedup_key = f"{contact_id}:referral_ask:{year}:{quarter}"

            if await dedup_exists(db, dedup_key):
                seen_contacts.add(contact_id)
                continue

            contact = await load_contact(db, contact_id)
            if contact is None:
                continue

            is_happy_client = contact.status == "converted"
            if not is_happy_client:
                won_result = await db.execute(
                    select(Opportunity.id)
                    .where(
                        Opportunity.workspace_id == context.workspace_id,
                        Opportunity.primary_contact_id == contact_id,
                        Opportunity.status == "won",
                    )
                    .limit(1)
                )
                is_happy_client = won_result.scalar_one_or_none() is not None

            if not is_happy_client:
                continue

            seen_contacts.add(contact_id)
            name = contact.full_name
            days_since = (now - appt.scheduled_at).days

            nudge = HumanNudge(
                workspace_id=context.workspace_id,
                contact_id=contact_id,
                nudge_type="referral_ask",
                title=f"Ask {name} for a referral",
                message=(
                    f"It's been {days_since} days since your meeting with {name}. "
                    f"Happy clients are your best lead source \u2014 ask for a referral."
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
