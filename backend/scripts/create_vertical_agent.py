#!/usr/bin/env python
"""Create or update a CRM agent for a vertical site.

Reads a vertical registry JSON file, builds a system prompt from the config,
and creates (or updates) the agent in the database with embed enabled.

Usage:
    cd backend && uv run python scripts/create_vertical_agent.py /path/to/registry/painters.json

For production (via Railway):
    cd /home/groot/aicrm
    railway run -- bash -c \
      "cd backend && python scripts/create_vertical_agent.py /path/to/config.json"
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.agent import Agent, generate_public_id

DEMO_WORKSPACE_ID = settings.demo_workspace_id


def build_system_prompt(config: dict) -> str:
    """Build a full system prompt from vertical registry config."""
    brand = config["brandName"]
    industry = config["industry"]
    agent_notes = config["agent"]["systemPromptNotes"]
    project_types = industry["projectTypes"]

    project_list = "\n".join(f"  - {pt}" for pt in project_types)
    software_list = ", ".join(industry["commonSoftware"])
    lead_sources = ", ".join(industry["leadSources"])

    return f"""\
# Role & Identity
You are an AI receptionist for {brand}. You help {industry["name"]} manage \
incoming calls and inquiries.

# Your Purpose
- Answer calls professionally and warmly
- Qualify leads by gathering project details
- Book estimates/consultations on the calendar
- Provide basic information about services

# Qualification Questions
Ask about:
- Project type:
{project_list}
- Timeline
- Property type (residential/commercial)
- Budget range (if appropriate)
- Preferred contact method

# Industry Context
- Average project value: {industry["avgTicket"]}
- Common software they use: {software_list}
- Typical lead sources: {lead_sources}

# Personality
{agent_notes}

# Rules
- Never claim to be human
- If you can't answer a question, offer to have someone call them back
- Always try to book an appointment before ending the call
- Be concise but friendly

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

The ONLY way to check times is check_availability. The ONLY way to book is \
book_appointment. Call them IMMEDIATELY - no announcements, no delays."""


def build_initial_greeting(config: dict) -> str:
    """Build a vertical-specific initial greeting."""
    brand = config["brandName"]
    industry_short = config["industry"]["shortName"]
    return (
        f"Hi there! Thanks for reaching out to {brand}. "
        f"I'm your AI assistant here to help with all your {industry_short.lower()} needs. "
        f"How can I help you today?"
    )


async def create_or_update_vertical_agent(session: AsyncSession, config: dict) -> Agent:
    """Create or update the vertical agent."""
    if not DEMO_WORKSPACE_ID:
        print("ERROR: DEMO_WORKSPACE_ID not set in environment", file=sys.stderr)
        sys.exit(1)

    workspace_id = uuid.UUID(DEMO_WORKSPACE_ID)
    agent_name = f"{config['brandName']} AI Receptionist"
    domain = config["domain"]

    # Check if agent already exists for this vertical
    stmt = select(Agent).where(
        Agent.workspace_id == workspace_id,
        Agent.name == agent_name,
    )
    result = await session.execute(stmt)
    existing_agent = result.scalar_one_or_none()

    system_prompt = build_system_prompt(config)
    initial_greeting = build_initial_greeting(config)

    embed_settings = {
        "button_text": f"Chat with {config['brandName']}",
        "primary_color": config["theme"]["primary"],
        "position": "bottom-right",
        "mode": "both",
    }

    allowed_domains = [domain, f"*.{domain}", "localhost"]

    if existing_agent:
        print(f"Found existing agent: {existing_agent.id}", file=sys.stderr)
        print("Updating configuration...", file=sys.stderr)

        existing_agent.channel_mode = "both"
        existing_agent.voice_provider = config["agent"].get("voiceProvider", "openai")
        existing_agent.voice_id = config["agent"]["voiceId"]
        existing_agent.system_prompt = system_prompt
        existing_agent.initial_greeting = initial_greeting
        existing_agent.enabled_tools = ["book_appointment"]
        existing_agent.embed_enabled = True
        existing_agent.allowed_domains = allowed_domains
        existing_agent.embed_settings = embed_settings
        existing_agent.is_active = True

        if not existing_agent.public_id:
            existing_agent.public_id = generate_public_id()

        await session.commit()
        await session.refresh(existing_agent)

        print("Agent updated successfully!", file=sys.stderr)
        return existing_agent

    else:
        print(f"Creating new agent: {agent_name}", file=sys.stderr)

        agent = Agent(
            workspace_id=workspace_id,
            name=agent_name,
            description=(
                f"AI receptionist for {config['brandName']} — "
                f"handles calls and chat for {config['industry']['name']}."
            ),
            channel_mode="both",
            voice_provider=config["agent"].get("voiceProvider", "openai"),
            voice_id=config["agent"]["voiceId"],
            language="en-US",
            turn_detection_mode="server_vad",
            turn_detection_threshold=0.5,
            silence_duration_ms=500,
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=2000,
            initial_greeting=initial_greeting,
            text_response_delay_ms=30_000,
            text_max_context_messages=20,
            enabled_tools=["book_appointment"],
            is_active=True,
            public_id=generate_public_id(),
            embed_enabled=True,
            allowed_domains=allowed_domains,
            embed_settings=embed_settings,
        )

        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        print("Agent created successfully!", file=sys.stderr)
        return agent


async def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 2:
        print(
            "Usage: python scripts/create_vertical_agent.py /path/to/registry/slug.json",
            file=sys.stderr,
        )
        sys.exit(1)

    config_path = Path(sys.argv[1])
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = json.loads(config_path.read_text())

    print(f"Creating agent for vertical: {config['slug']}", file=sys.stderr)
    print(f"Brand: {config['brandName']}", file=sys.stderr)
    print(f"Domain: {config['domain']}", file=sys.stderr)
    print(file=sys.stderr)

    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        agent = await create_or_update_vertical_agent(session, config)

        # Output JSON to stdout (only machine-readable output goes to stdout)
        output = {
            "agent_id": str(agent.id),
            "public_id": agent.public_id,
            "name": agent.name,
            "embed_enabled": agent.embed_enabled,
            "allowed_domains": agent.allowed_domains,
        }
        print(json.dumps(output))

        # Human-readable details to stderr
        print(file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("AGENT DETAILS", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"ID:              {agent.id}", file=sys.stderr)
        print(f"Public ID:       {agent.public_id}", file=sys.stderr)
        print(f"Name:            {agent.name}", file=sys.stderr)
        print(f"Voice Provider:  {agent.voice_provider}", file=sys.stderr)
        print(f"Voice ID:        {agent.voice_id}", file=sys.stderr)
        print(f"Channel Mode:    {agent.channel_mode}", file=sys.stderr)
        print(f"Embed Enabled:   {agent.embed_enabled}", file=sys.stderr)
        print(f"Allowed Domains: {agent.allowed_domains}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
