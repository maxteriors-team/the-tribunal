"""Context builder for multi-armed bandit decision-making."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.conversation import Conversation


def _get_time_of_day(dt: datetime) -> str:
    """Categorize time of day based on hour."""
    hour = dt.hour
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


def _get_day_of_week(dt: datetime) -> str:
    """Get lowercase day of week name."""
    return dt.strftime("%A").lower()


def _get_lead_score_bucket(lead_score: int) -> str:
    """Categorize lead score into buckets."""
    if lead_score >= 80:
        return "high"
    elif lead_score >= 40:
        return "medium"
    else:
        return "low"


async def build_decision_context(
    db: AsyncSession,
    contact_id: int | None,
    agent_id: uuid.UUID,
    call_time: datetime,
) -> dict[str, object]:
    """Build context snapshot for bandit arm selection.

    Captures relevant features at decision time that may influence
    which prompt version performs best.

    Args:
        db: Database session
        contact_id: Contact ID (optional for inbound calls without contact match)
        agent_id: Agent ID making the call
        call_time: Time of the call

    Returns:
        Context dictionary with categorized features
    """
    context: dict[str, object] = {
        "time_of_day": _get_time_of_day(call_time),
        "day_of_week": _get_day_of_week(call_time),
        "hour": call_time.hour,
        "agent_id": str(agent_id),
    }

    if contact_id is None:
        # Inbound call without contact match
        context["contact_segment"] = "unknown"
        context["prior_contact_count"] = 0
        context["lead_score_bucket"] = "unknown"
        context["is_qualified"] = False
        return context

    # Fetch contact data
    contact_result = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = contact_result.scalar_one_or_none()

    if contact is None:
        context["contact_segment"] = "unknown"
        context["prior_contact_count"] = 0
        context["lead_score_bucket"] = "unknown"
        context["is_qualified"] = False
        return context

    # Count prior conversations with this contact (across all agents for this contact)
    prior_count_result = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.contact_id == contact_id)
    )
    prior_contact_count = prior_count_result.scalar() or 0

    # Determine contact segment
    if contact.status == "new" and prior_contact_count == 0:
        contact_segment = "new"
    elif contact.is_qualified:
        contact_segment = "qualified"
    elif prior_contact_count > 0:
        contact_segment = "returning"
    else:
        contact_segment = "new"

    context["contact_segment"] = contact_segment
    context["prior_contact_count"] = prior_contact_count
    context["lead_score_bucket"] = _get_lead_score_bucket(contact.lead_score)
    context["is_qualified"] = contact.is_qualified
    context["contact_status"] = contact.status

    # Add enrichment status if available
    if contact.enrichment_status:
        context["is_enriched"] = contact.enrichment_status == "enriched"

    return context
