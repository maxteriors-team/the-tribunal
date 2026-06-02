#!/usr/bin/env python
"""Enable Cal.com booking for the 4 demo agents (Rachel, Amy, Tina, Mike).

Sets calcom_event_type_id and adds book_appointment to enabled_tools.

Usage:
    cd backend && uv run python scripts/update_demo_agents_calcom.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.agent import Agent

# Use DATABASE_PUBLIC_URL if set (for running locally against Railway),
# otherwise fall back to settings.database_url.
_public_url = os.environ.get("DATABASE_PUBLIC_URL", "")
if _public_url:
    # Ensure asyncpg driver
    DB_URL = _public_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DB_URL = settings.database_url

CALCOM_EVENT_TYPE_ID = 4453549

DEMO_AGENTS = {
    "ag_LXptHpWq": "Rachel (Dobi Real Estate)",
    "ag_l28wHbyl": "Amy (Marian Grout Real Estate)",
    "ag_72ObhPOO": "Tina (22 Title)",
    "ag_g0bjj8NZ": "Mike (Rhino Building)",
}


async def main() -> None:
    print("=" * 60)
    print("Enabling Cal.com Booking for Demo Agents")
    print("=" * 60)
    print()

    engine = create_async_engine(DB_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        for public_id, label in DEMO_AGENTS.items():
            result = await session.execute(
                select(Agent).where(Agent.public_id == public_id)
            )
            agent = result.scalar_one_or_none()

            if not agent:
                print(f"WARNING: {label} ({public_id}) not found — skipping")
                continue

            # Set cal.com event type
            agent.calcom_event_type_id = CALCOM_EVENT_TYPE_ID

            # Add book_appointment to enabled_tools if not already present
            tools = list(agent.enabled_tools or [])
            if "book_appointment" not in tools:
                tools.append("book_appointment")
                agent.enabled_tools = tools

            print(f"✓ {label} ({public_id})")
            print(f"  calcom_event_type_id = {agent.calcom_event_type_id}")
            print(f"  enabled_tools = {agent.enabled_tools}")
            print()

        await session.commit()
        print("All changes committed.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
