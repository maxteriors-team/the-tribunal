"""Message context builder for AI conversations.

Handles:
- Building conversation message history for LLM context
- Extracting email addresses from message history
- Fetching workspace timezone settings
- Loading offer context from campaign associations
- Generating Cal.com booking URLs with pre-filled contact info
"""

import re
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.campaign import CampaignContact
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.workspace import Workspace

logger = structlog.get_logger()

# Default timezone fallback
DEFAULT_TIMEZONE = "America/New_York"


async def get_workspace_timezone(
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """Get timezone from workspace settings.

    Args:
        workspace_id: The workspace ID
        db: Database session

    Returns:
        Timezone string (e.g., "America/New_York")
    """
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace and workspace.settings:
        tz = workspace.settings.get("timezone")
        if isinstance(tz, str):
            return tz
    return DEFAULT_TIMEZONE


def extract_email_from_messages(messages: list[dict[str, str]]) -> str | None:
    """Extract email address from conversation history.

    Searches through messages (newest first) for email addresses.

    Args:
        messages: List of message dicts with 'content' key

    Returns:
        The most recently mentioned email address, or None
    """
    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

    # Search from newest to oldest (reversed)
    for msg in reversed(messages):
        content = msg.get("content", "")
        match = re.search(email_pattern, content)
        if match:
            return match.group(0)

    return None


async def build_message_context(
    conversation: Conversation,
    db: AsyncSession,
    max_messages: int = 20,
) -> list[dict[str, str]]:
    """Build message history for LLM context.

    Args:
        conversation: The conversation
        db: Database session
        max_messages: Maximum messages to include

    Returns:
        List of message dicts in OpenAI format
    """
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    )
    messages = list(reversed(result.scalars().all()))

    context: list[dict[str, str]] = []
    for msg in messages:
        role = "user" if msg.direction == "inbound" else "assistant"
        context.append({"role": role, "content": msg.body})

    return context


async def get_offer_context(
    conversation: Conversation,
    db: AsyncSession,
) -> str | None:
    """Get offer context for a conversation from its campaign.

    Args:
        conversation: The conversation
        db: Database session

    Returns:
        Formatted offer context string, or None if no offer
    """
    from sqlalchemy.orm import selectinload

    from app.models.campaign import Campaign

    # Get campaign contact for this conversation
    result = await db.execute(
        select(CampaignContact)
        .options(selectinload(CampaignContact.campaign).selectinload(Campaign.offer))
        .where(CampaignContact.conversation_id == conversation.id)
        .order_by(CampaignContact.created_at.desc())
        .limit(1)
    )
    campaign_contact = result.scalar_one_or_none()

    if not campaign_contact or not campaign_contact.campaign or not campaign_contact.campaign.offer:
        return None

    offer = campaign_contact.campaign.offer

    # Format discount text
    discount_text = ""
    if offer.discount_type == "percentage":
        discount_text = f"{offer.discount_value}% off"
    elif offer.discount_type == "fixed":
        discount_text = f"${offer.discount_value} off"
    elif offer.discount_type == "free_service":
        discount_text = "Free service"

    # Build context string
    context_parts = [f"The customer was offered: {offer.name}"]

    if discount_text:
        context_parts.append(f"Discount: {discount_text}")

    if offer.description:
        context_parts.append(f"Description: {offer.description}")

    if offer.terms:
        context_parts.append(f"Terms: {offer.terms}")

    context_parts.append("Refer to this offer in your responses if relevant to the conversation.")

    return "\n".join(context_parts)


async def get_booking_url(
    agent: Agent,
    conversation: Conversation,
    db: AsyncSession,
) -> str | None:
    """Get Cal.com booking URL for an agent with pre-filled contact information.

    Args:
        agent: The agent with potential calcom_event_type_id
        conversation: The conversation
        db: Database session

    Returns:
        Cal.com booking URL with pre-filled parameters, or None if not configured
    """
    from app.utils.calendar import generate_booking_url

    # Check if agent has a Cal.com event type configured
    if not agent.calcom_event_type_id:
        return None

    # Try to get contact info if available
    contact_email: str | None = None
    contact_name: str | None = None

    # Load contact if conversation has one
    if conversation.contact_id:
        result = await db.execute(select(Contact).where(Contact.id == conversation.contact_id))
        contact = result.scalar_one_or_none()
        if contact:
            contact_email = contact.email
            contact_name = contact.full_name

    # Build the booking URL with contact pre-fill
    booking_url = generate_booking_url(
        event_type_id=agent.calcom_event_type_id,
        contact_email=contact_email,
        contact_name=contact_name,
        contact_phone=conversation.contact_phone,
    )

    return booking_url
