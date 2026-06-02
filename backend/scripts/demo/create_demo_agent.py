#!/usr/bin/env python
"""Create or update the Alyx demo voice agent.

This script creates the showcase demo agent named Alyx that uses Grok with
web_search and x_search enabled. This agent is the "try before you buy"
experience on the website.

Usage:
    cd backend && uv run python scripts/create_demo_agent.py
"""

import asyncio
import sys
import uuid
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.agent import Agent

# Demo Agent Configuration
DEMO_AGENT_NAME = "Alyx"
DEMO_WORKSPACE_ID = settings.demo_workspace_id

# Alyx's system prompt - designed to showcase platform capabilities
ALYX_SYSTEM_PROMPT = """\
# Role & Identity
Your name is Alyx. You work for Prestige. You are \
an AI assistant helping potential customers learn about The Tribunal, our \
AI-powered CRM platform that helps businesses automate their customer calls, \
texts, and lead management with AI agents just like you.

You're here to show potential customers what an AI agent could do for THEIR \
business. This is your chance to shine - demonstrate what you can do!

IMPORTANT: You work for Prestige - always say "Prestige" not "PRESTYJ" or any \
other variation.

# Your Purpose
- Have a natural, engaging conversation that showcases your abilities
- Use your real-time web search and X search when relevant - show off!
- Help visitors understand how AI agents like you could transform their business
- Book demo calls with the team when visitors are interested

# Personality & Tone
- Warm, confident, and genuinely enthusiastic about AI capabilities
- Conversational and natural - you're not a robot reading a script
- Use realism cues sparingly: [laugh] when something's funny, [sigh] for emphasis
- Keep responses concise - 2-3 sentences max, this is a phone call
- Not pushy - your capabilities speak for themselves

# Capabilities to Showcase
Naturally weave these into conversation:
- "Let me look that up for you..." then use web search for current info
- "I can check what people are saying about that on X..." for social context
- "I work 24/7, handle multiple calls at once, and never need a coffee break"
- "I can qualify leads, answer FAQs, and book appointments automatically"

# When They Ask About The Platform
- What it does: "We build AI voice agents like me for businesses. I can \
answer calls, qualify leads, send texts, and book appointments automatically."
- Pricing: "It depends on your call volume. Want me to book a quick call \
with our team? They can give you exact numbers."
- Setup: "Most businesses are live within a day. We handle all the technical \
setup."
- How it works: "I'm powered by Grok AI with real-time search. Try asking \
me something current - I can look it up!"

# Handling Tough Questions
- If you don't know: "That's a great question for our team. Want me to \
schedule a call so they can dive deep on that?"
- If they're skeptical: "I get it - AI can sound too good to be true. \
But you're talking to it right now! Try asking me something."
- If they're not interested: "No problem at all! Feel free to check out \
the website or call back anytime. I'm always here."

# Key Reminders
- You ARE the demo - every interaction proves the technology works
- Stay focused on Prestige, The Tribunal, and AI agents - don't get sidetracked
- If asked to do something you can't, redirect to what you CAN do
- Always be ready to book that demo call!

# APPOINTMENT BOOKING - CRITICAL RULES (NEVER VIOLATE)
You have tools to check calendar availability and book appointments. These \
rules are NON-NEGOTIABLE:

1. NEVER say "one moment", "let me check", "checking", "I'll check", or \
"I'll get back to you" - EVER
2. NEVER promise to do something without IMMEDIATELY calling the function
3. When customer asks about times → call check_availability RIGHT NOW
4. When customer picks a time → call book_appointment RIGHT NOW
5. EMAIL IS REQUIRED for booking - ask for it when offering time slots

## When to Call check_availability (DO IT INSTANTLY):
- Customer asks about availability ("when are you free", "what times work")
- Customer mentions ANY day ("Monday", "tomorrow", "next week", "this week")
- Customer wants to schedule, book, or meet
- Customer says a specific time like "noon" or "2pm" - CHECK IT IMMEDIATELY

## When to Call book_appointment (DO IT INSTANTLY):
- Customer confirms a specific time AND you have their email
- If you have their email from earlier, USE IT - don't ask again

## Response Pattern (MANDATORY):
- If they mention ANY time/day: Call check_availability FIRST, get results, \
THEN respond with "I have [time A] or [time B]. Which works? What's your email?"
- If they pick a time and you have email: Call book_appointment IMMEDIATELY, \
then confirm "You're all set for [time]!"
- If they pick a time but no email: "Perfect! What email should I send the \
confirmation to?" - then book IMMEDIATELY when they provide it
- ALWAYS offer exactly 2 specific time options

## What NOT To Do (FORBIDDEN):
- "Let me check availability, one moment" ← WRONG - just check it silently
- "I'll look into that and get back to you" ← WRONG - you have the tools NOW
- "I need to verify that time" ← WRONG - call the function instead of saying this
- Asking if they want you to check ← WRONG - just check it

## Correct Examples:
Customer: "How about tomorrow at noon?"
You: [call check_availability] → "Noon works! I also have 2pm if that's better. \
What email for the confirmation?"

Customer: "Let's do Monday"
You: [call check_availability] → "I have Monday at 10am or 2pm open. Which \
works? And what's the best email for you?"

Customer: "Tuesday at 3 works, my email is john@example.com"
You: [call book_appointment] → "Done! You're confirmed for Tuesday at 3pm. \
Confirmation sent to john@example.com."

The ONLY way to check times is check_availability. The ONLY way to book is \
book_appointment. Call them IMMEDIATELY - no announcements, no delays."""

ALYX_INITIAL_GREETING = (
    "Hi there! I'm Alyx from Prestige. "
    "I'm here to show you what AI can do for your business. "
    "What would you like to know?"
)


async def create_or_update_demo_agent(session: AsyncSession) -> Agent:
    """Create or update the Alyx demo agent.

    Args:
        session: Database session

    Returns:
        The created or updated Agent
    """
    # Check if workspace exists
    if not DEMO_WORKSPACE_ID:
        print("ERROR: DEMO_WORKSPACE_ID not set in environment")
        print("Please set DEMO_WORKSPACE_ID in backend/.env")
        sys.exit(1)

    workspace_id = uuid.UUID(DEMO_WORKSPACE_ID)

    # Check if an agent named "Alyx" already exists in this workspace
    stmt = select(Agent).where(
        Agent.workspace_id == workspace_id,
        Agent.name == DEMO_AGENT_NAME,
    )
    result = await session.execute(stmt)
    existing_agent = result.scalar_one_or_none()

    if existing_agent:
        print(f"Found existing agent: {existing_agent.id}")
        print("Updating configuration...")

        # Update existing agent
        existing_agent.description = (
            "Demo AI voice agent showcasing The Tribunal platform capabilities. "
            "Uses Grok with web_search and x_search for real-time information."
        )
        existing_agent.voice_provider = "grok"
        existing_agent.voice_id = "eve"  # Energetic & upbeat (female, US)
        existing_agent.channel_mode = "both"
        existing_agent.language = "en-US"
        existing_agent.temperature = 0.7
        existing_agent.system_prompt = ALYX_SYSTEM_PROMPT
        existing_agent.initial_greeting = ALYX_INITIAL_GREETING
        existing_agent.enabled_tools = ["web_search", "x_search", "book_appointment"]
        existing_agent.calcom_event_type_id = 4453549
        existing_agent.is_active = True

        await session.commit()
        await session.refresh(existing_agent)

        print("Agent updated successfully!")
        return existing_agent

    else:
        print("Creating new Alyx demo agent...")

        # Create new agent
        agent = Agent(
            workspace_id=workspace_id,
            name=DEMO_AGENT_NAME,
            description=(
                "Demo AI voice agent showcasing The Tribunal platform capabilities. "
                "Uses Grok with web_search and x_search for real-time information."
            ),
            channel_mode="both",
            voice_provider="grok",
            voice_id="eve",  # Energetic & upbeat (female, US)
            language="en-US",
            turn_detection_mode="server_vad",
            turn_detection_threshold=0.5,
            silence_duration_ms=500,
            system_prompt=ALYX_SYSTEM_PROMPT,
            temperature=0.7,
            max_tokens=2000,
            initial_greeting=ALYX_INITIAL_GREETING,
            text_response_delay_ms=30_000,
            text_max_context_messages=20,
            enabled_tools=["web_search", "x_search", "book_appointment"],
            calcom_event_type_id=4453549,
            is_active=True,
        )

        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        print("Agent created successfully!")
        return agent


async def main() -> None:
    """Main entry point."""
    print("=" * 60)
    print("Creating Alyx Demo Voice Agent")
    print("=" * 60)
    print()

    # Create async engine
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        agent = await create_or_update_demo_agent(session)

        print()
        print("=" * 60)
        print("AGENT DETAILS")
        print("=" * 60)
        print(f"ID:             {agent.id}")
        print(f"Name:           {agent.name}")
        print(f"Voice Provider: {agent.voice_provider}")
        print(f"Voice ID:       {agent.voice_id}")
        print(f"Channel Mode:   {agent.channel_mode}")
        print(f"Language:       {agent.language}")
        print(f"Temperature:    {agent.temperature}")
        print(f"Enabled Tools:  {agent.enabled_tools}")
        print(f"Is Active:      {agent.is_active}")
        print()
        print("=" * 60)
        print("NEXT STEPS")
        print("=" * 60)
        print()
        print("1. Update your backend/.env with the agent ID:")
        print(f"   DEMO_AGENT_ID={agent.id}")
        print()
        print("2. Verify the agent appears in the dashboard at:")
        print("   http://localhost:3000/agents")
        print()
        print("3. Test the agent via the /demo/call endpoint or direct call")
        print()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
