#!/usr/bin/env python3
"""Upload the Dead Lead Reactivation Scripts lead magnet to the CRM."""

import asyncio
import sys
sys.path.insert(0, '/home/groot/aicrm/backend')

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.lead_magnet import LeadMagnet, LeadMagnetType, DeliveryMethod

WORKSPACE_ID = "ba0e0e99-c7c9-45ec-9625-567d54d6e9c2"  # PRESTYJ workspace
PDF_PATH = "/static/lead-magnets/dead-lead-reactivation-scripts.pdf"


async def upload_lead_magnet():
    """Create the lead magnet record in the database."""
    async with AsyncSessionLocal() as db:
        # Check if it already exists
        result = await db.execute(
            select(LeadMagnet).where(
                LeadMagnet.workspace_id == WORKSPACE_ID,
                LeadMagnet.name == "Dead Lead Reactivation Scripts"
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            print(f"Lead magnet already exists: {existing.id}")
            print(f"  Name: {existing.name}")
            print(f"  URL: {existing.content_url}")
            print(f"  Downloads: {existing.download_count}")
            return existing

        # Create new lead magnet
        lead_magnet = LeadMagnet(
            workspace_id=WORKSPACE_ID,
            name="Dead Lead Reactivation Scripts",
            description="7 proven scripts to wake up your database - combining NEPQ (Jeremy Miner), Value-First (Alex Hormozi), and Reverse Selling (Brandon Mulrenin) methodologies.",
            magnet_type=LeadMagnetType.PDF.value,
            delivery_method=DeliveryMethod.DOWNLOAD.value,
            content_url=PDF_PATH,
            estimated_value=297.0,  # Hormozi-style value perception
            is_active=True,
        )

        db.add(lead_magnet)
        await db.commit()
        await db.refresh(lead_magnet)

        print("=" * 60)
        print("LEAD MAGNET UPLOADED SUCCESSFULLY")
        print("=" * 60)
        print(f"  ID: {lead_magnet.id}")
        print(f"  Name: {lead_magnet.name}")
        print(f"  Type: {lead_magnet.magnet_type}")
        print(f"  Delivery: {lead_magnet.delivery_method}")
        print(f"  URL: {lead_magnet.content_url}")
        print(f"  Estimated Value: ${lead_magnet.estimated_value}")
        print("=" * 60)

        return lead_magnet


if __name__ == "__main__":
    asyncio.run(upload_lead_magnet())
