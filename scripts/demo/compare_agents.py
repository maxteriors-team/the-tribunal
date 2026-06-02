#!/usr/bin/env python3
"""Compare Jess and Chloe agent prompts and optionally update Jess."""

import asyncio
import sys
sys.path.insert(0, '/home/groot/aicrm/backend')

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.agent import Agent

# Agent IDs from stress test files
JESS_AGENT_ID = "5bba3103-f3e0-4eb8-bec0-5423bf4051d4"
CHLOE_AGENT_ID = "7e07edb5-8a41-4d7d-a836-880cb33529b9"


async def fetch_agents():
    """Fetch both agents from the database."""
    async with AsyncSessionLocal() as db:
        # Fetch Jess
        result = await db.execute(
            select(Agent).where(Agent.id == JESS_AGENT_ID)
        )
        jess = result.scalar_one_or_none()

        # Fetch Chloe
        result = await db.execute(
            select(Agent).where(Agent.id == CHLOE_AGENT_ID)
        )
        chloe = result.scalar_one_or_none()

        return jess, chloe


async def main():
    jess, chloe = await fetch_agents()

    print("=" * 80)
    print("AGENT COMPARISON")
    print("=" * 80)

    if jess:
        print(f"\n### JESS (PRESTYJ Sales Agent) ###")
        print(f"ID: {jess.id}")
        print(f"Name: {jess.name}")
        print(f"Channel Mode: {jess.channel_mode}")
        print(f"Temperature: {jess.temperature}")
        print(f"Enabled Tools: {jess.enabled_tools}")
        print(f"\n--- SYSTEM PROMPT ({len(jess.system_prompt)} chars) ---")
        print(jess.system_prompt)
    else:
        print("\nJess agent NOT FOUND!")

    print("\n" + "=" * 80)

    if chloe:
        print(f"\n### CHLOE (Marian Grout Listing Coordinator) ###")
        print(f"ID: {chloe.id}")
        print(f"Name: {chloe.name}")
        print(f"Channel Mode: {chloe.channel_mode}")
        print(f"Temperature: {chloe.temperature}")
        print(f"Enabled Tools: {chloe.enabled_tools}")
        print(f"\n--- SYSTEM PROMPT ({len(chloe.system_prompt)} chars) ---")
        print(chloe.system_prompt)
    else:
        print("\nChloe agent NOT FOUND!")


if __name__ == "__main__":
    asyncio.run(main())
