"""AI-powered SMS fallback message generation for voice campaigns.

Generates contextual SMS messages after failed voice calls using OpenAI.
"""

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import Agent
from app.models.campaign import Campaign
from app.models.contact import Contact

logger = structlog.get_logger()


async def generate_sms_fallback_message(
    db: AsyncSession,
    campaign: Campaign,
    contact: Contact,
    call_outcome: str,
    openai_api_key: str | None = None,
) -> str:
    """Generate AI-powered SMS fallback message after failed call.

    Args:
        db: Database session
        campaign: Voice campaign
        contact: Contact who didn't answer
        call_outcome: Why call failed (no_answer, busy, voicemail, rejected)
        openai_api_key: OpenAI API key (defaults to settings)

    Returns:
        Generated SMS message text

    Raises:
        ValueError: If OpenAI API key is not configured
    """
    log = logger.bind(
        campaign_id=str(campaign.id),
        contact_id=contact.id,
        call_outcome=call_outcome,
    )

    api_key = openai_api_key or settings.openai_api_key
    if not api_key:
        raise ValueError("OpenAI API key required for AI fallback")

    # Get the agent's system prompt if configured
    agent = None
    if campaign.sms_fallback_agent_id:
        result = await db.execute(select(Agent).where(Agent.id == campaign.sms_fallback_agent_id))
        agent = result.scalar_one_or_none()

    # Build context for AI
    call_context_map = {
        "no_answer": "We tried calling but they didn't answer the phone.",
        "busy": "Their line was busy when we called.",
        "voicemail": "We reached their voicemail.",
        "rejected": "They declined or rejected our call.",
    }
    call_context = call_context_map.get(call_outcome, "We couldn't reach them by phone.")

    # Build contact name
    contact_name = " ".join(filter(None, [contact.first_name, contact.last_name])) or "there"

    # Build system prompt for SMS generation
    agent_context = ""
    if agent and agent.system_prompt:
        agent_context = f"\n\nAgent personality and instructions:\n{agent.system_prompt}"

    system_prompt = f"""You are sending an SMS follow-up after a failed phone call attempt.

Contact Information:
- Name: {contact_name}
- Company: {contact.company_name or "Unknown"}
- Email: {contact.email or "Not provided"}

Campaign: {campaign.name}
{f"Campaign description: {campaign.description}" if campaign.description else ""}

Reason for SMS: {call_context}
{agent_context}

Write a SHORT SMS message (under 160 characters) that:
1. Briefly acknowledges you tried to call
2. Provides value or mentions why you're reaching out
3. Invites them to respond or take action

Rules:
- Do NOT use markdown formatting
- Do NOT use emojis unless the agent instructions specifically request them
- Keep it conversational and professional
- Plain text only
- Be concise - SMS should be short"""

    log.info("generating_ai_fallback_message")

    try:
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=[{"role": "system", "content": system_prompt}],
            max_completion_tokens=100,
            temperature=0.7,
        )

        message_text = response.choices[0].message.content or ""
        message_text = message_text.strip()

        # Ensure message isn't too long for SMS
        if len(message_text) > 160:
            # Truncate intelligently at word boundary
            message_text = message_text[:157].rsplit(" ", 1)[0] + "..."

        log.info(
            "ai_fallback_message_generated",
            message_length=len(message_text),
        )

        return message_text

    except Exception as e:
        log.exception("ai_fallback_generation_error", error=str(e))
        raise
