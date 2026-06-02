#!/usr/bin/env python
"""Enable embed settings on the Alyx demo agent.

Sets embed_enabled, allowed_domains, and embed_settings so the agent
can be embedded via iframe on prestyj.com/demo.

Usage:
    cd backend && uv run python scripts/enable_demo_embed.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.agent import Agent, generate_public_id

DEMO_WORKSPACE_ID = settings.demo_workspace_id


async def main() -> None:
    engine = create_async_engine(str(settings.database_url), echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(
            select(Agent).where(
                Agent.workspace_id == DEMO_WORKSPACE_ID,
                Agent.name == "Alyx",
            )
        )
        agent = result.scalar_one_or_none()

        if not agent:
            print("ERROR: Alyx agent not found in demo workspace")
            sys.exit(1)

        print(f"Found Alyx agent: {agent.id}")

        # Ensure public_id exists
        if not agent.public_id:
            agent.public_id = generate_public_id()
            print(f"Generated new public_id: {agent.public_id}")
        else:
            print(f"Existing public_id: {agent.public_id}")

        # Enable embed
        agent.embed_enabled = True
        agent.allowed_domains = [
            "prestyj.com",
            "*.prestyj.com",
            "localhost",
            "localhost:3000",
        ]
        agent.embed_settings = {
            "button_text": "Talk to Alyx",
            "theme": "dark",
            "position": "bottom-right",
            "primary_color": "#7058e3",
        }

        await session.commit()
        print(f"\nEmbed enabled successfully!")
        print(f"  public_id: {agent.public_id}")
        print(f"  embed_enabled: {agent.embed_enabled}")
        print(f"  allowed_domains: {agent.allowed_domains}")
        print(f"  embed_settings: {agent.embed_settings}")


if __name__ == "__main__":
    asyncio.run(main())
