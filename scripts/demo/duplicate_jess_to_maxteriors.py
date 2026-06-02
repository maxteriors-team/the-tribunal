#!/usr/bin/env python3
"""Duplicate JESS agent to maxteriors workspace."""

import asyncio
import sys
import uuid

sys.path.insert(0, "/home/groot/aicrm/backend")

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.workspace import Workspace


JESS_AGENT_ID = "5bba3103-f3e0-4eb8-bec0-5423bf4051d4"
MAXTERIORS_SLUG = "maxteriors"


async def get_or_create_maxteriors_workspace(db) -> Workspace:
    """Find existing maxteriors workspace or create it."""
    result = await db.execute(
        select(Workspace).where(Workspace.slug == MAXTERIORS_SLUG)
    )
    workspace = result.scalar_one_or_none()

    if workspace:
        print(f"✅ Found existing maxteriors workspace: {workspace.id}")
        return workspace

    # Create the workspace
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Maxteriors",
        slug=MAXTERIORS_SLUG,
        description="Maxteriors AI CRM Workspace",
        settings={"timezone": "America/New_York"},
        is_active=True,
    )
    db.add(workspace)
    await db.flush()  # Get the ID without committing
    print(f"✅ Created new maxteriors workspace: {workspace.id}")
    return workspace


async def duplicate_jess_agent():
    """Duplicate JESS agent to maxteriors workspace."""
    async with AsyncSessionLocal() as db:
        # Get the JESS agent
        result = await db.execute(select(Agent).where(Agent.id == JESS_AGENT_ID))
        jess = result.scalar_one_or_none()

        if not jess:
            print("❌ ERROR: JESS agent not found!")
            return False

        print("=" * 80)
        print("DUPLICATING JESS AGENT TO MAXTERIORS")
        print("=" * 80)
        print(f"\nSource Agent: {jess.name} ({jess.id})")
        print(f"Source Workspace: {jess.workspace_id}")

        # Get or create maxteriors workspace
        maxteriors = await get_or_create_maxteriors_workspace(db)

        # Check if an agent already exists in maxteriors with same name
        existing = await db.execute(
            select(Agent).where(
                Agent.workspace_id == maxteriors.id,
                Agent.name == jess.name,
            )
        )
        existing_agent = existing.scalar_one_or_none()

        if existing_agent:
            print(f"\n⚠️  Agent '{jess.name}' already exists in maxteriors workspace!")
            print(f"   Existing ID: {existing_agent.id}")
            response = input("Update existing agent? (y/n): ").strip().lower()
            if response != "y":
                print("Aborted.")
                return False

            # Update existing agent with JESS settings
            target_agent = existing_agent
            print(f"\n📝 Updating existing agent...")
        else:
            # Create new agent
            target_agent = Agent(
                id=uuid.uuid4(),
                workspace_id=maxteriors.id,
            )
            db.add(target_agent)
            print(f"\n📝 Creating new agent...")

        # Copy all configurable fields from JESS
        target_agent.name = jess.name
        target_agent.description = jess.description
        target_agent.channel_mode = jess.channel_mode
        target_agent.voice_provider = jess.voice_provider
        target_agent.voice_id = jess.voice_id
        target_agent.language = jess.language
        target_agent.turn_detection_mode = jess.turn_detection_mode
        target_agent.turn_detection_threshold = jess.turn_detection_threshold
        target_agent.silence_duration_ms = jess.silence_duration_ms
        target_agent.system_prompt = jess.system_prompt
        target_agent.temperature = jess.temperature
        target_agent.max_tokens = jess.max_tokens
        target_agent.initial_greeting = jess.initial_greeting
        target_agent.text_response_delay_ms = jess.text_response_delay_ms
        target_agent.text_max_context_messages = jess.text_max_context_messages
        target_agent.calcom_event_type_id = jess.calcom_event_type_id
        target_agent.enabled_tools = jess.enabled_tools.copy() if jess.enabled_tools else []
        target_agent.tool_settings = dict(jess.tool_settings) if jess.tool_settings else {}
        target_agent.is_active = True
        # Reset embed settings for new agent (these should be configured separately)
        if not existing_agent:
            target_agent.public_id = None
            target_agent.embed_enabled = False
            target_agent.allowed_domains = []
            target_agent.embed_settings = {}
            # Reset stats for new agent
            target_agent.total_calls = 0
            target_agent.total_messages = 0

        await db.commit()

        print("\n" + "=" * 80)
        print("✅ AGENT DUPLICATED SUCCESSFULLY")
        print("=" * 80)
        print(f"\nNew Agent ID: {target_agent.id}")
        print(f"Workspace ID: {maxteriors.id}")
        print(f"Workspace Slug: {MAXTERIORS_SLUG}")
        print(f"\nAgent Name: {target_agent.name}")
        print(f"Voice Provider: {target_agent.voice_provider}")
        print(f"Voice ID: {target_agent.voice_id}")
        print(f"Channel Mode: {target_agent.channel_mode}")
        print(f"Enabled Tools: {target_agent.enabled_tools}")
        print(f"System Prompt Length: {len(target_agent.system_prompt)} chars")
        print(f"\nThe agent is now active in the maxteriors workspace.")

        return True


async def preview_jess():
    """Preview JESS agent settings without making changes."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Agent).where(Agent.id == JESS_AGENT_ID))
        jess = result.scalar_one_or_none()

        if not jess:
            print("❌ ERROR: JESS agent not found!")
            return

        print("=" * 80)
        print("JESS AGENT CONFIGURATION")
        print("=" * 80)
        print(f"\nAgent ID: {jess.id}")
        print(f"Workspace ID: {jess.workspace_id}")
        print(f"Name: {jess.name}")
        print(f"Description: {jess.description}")
        print(f"\n--- Voice Settings ---")
        print(f"Voice Provider: {jess.voice_provider}")
        print(f"Voice ID: {jess.voice_id}")
        print(f"Channel Mode: {jess.channel_mode}")
        print(f"Language: {jess.language}")
        print(f"\n--- Turn Detection ---")
        print(f"Mode: {jess.turn_detection_mode}")
        print(f"Threshold: {jess.turn_detection_threshold}")
        print(f"Silence Duration: {jess.silence_duration_ms}ms")
        print(f"\n--- LLM Settings ---")
        print(f"Temperature: {jess.temperature}")
        print(f"Max Tokens: {jess.max_tokens}")
        print(f"Text Response Delay: {jess.text_response_delay_ms}ms")
        print(f"Max Context Messages: {jess.text_max_context_messages}")
        print(f"\n--- Tools ---")
        print(f"Enabled Tools: {jess.enabled_tools}")
        print(f"Tool Settings: {jess.tool_settings}")
        print(f"\n--- Integration ---")
        print(f"Cal.com Event Type ID: {jess.calcom_event_type_id}")
        print(f"\n--- Embed Settings ---")
        print(f"Public ID: {jess.public_id}")
        print(f"Embed Enabled: {jess.embed_enabled}")
        print(f"Allowed Domains: {jess.allowed_domains}")
        print(f"\n--- Status ---")
        print(f"Is Active: {jess.is_active}")
        print(f"Total Calls: {jess.total_calls}")
        print(f"Total Messages: {jess.total_messages}")
        print(f"\n--- System Prompt ---")
        print(jess.system_prompt[:500] + "..." if len(jess.system_prompt) > 500 else jess.system_prompt)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Duplicate JESS agent to maxteriors workspace")
    parser.add_argument("--preview", action="store_true", help="Preview JESS settings without duplicating")
    args = parser.parse_args()

    if args.preview:
        asyncio.run(preview_jess())
    else:
        asyncio.run(duplicate_jess_agent())
