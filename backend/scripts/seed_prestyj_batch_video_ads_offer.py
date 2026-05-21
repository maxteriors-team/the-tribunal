"""Seed Prestyj's reusable Batch Video Ads offer template."""

import argparse
import asyncio
import os
import uuid
from dataclasses import dataclass
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.offer import Offer

DEFAULT_WORKSPACE_ID = uuid.UUID(
    os.environ.get("DEFAULT_WORKSPACE_ID", "ba0e0e99-c7c9-45ec-9625-567d54d6e9c2")
)
PRESTYJ_BATCH_VIDEO_ADS_PUBLIC_SLUG = "prestyj-batch-video-ads"


class OfferValueStackItem(TypedDict):
    """JSON shape stored in Offer.value_stack_items."""

    name: str
    description: str
    value: float
    included: bool


@dataclass(frozen=True, slots=True)
class OfferTemplate:
    """Reusable offer template fields for an Offer row."""

    name: str
    description: str
    discount_type: str
    discount_value: float
    terms: str
    headline: str
    subheadline: str
    regular_price: float
    offer_price: float
    savings_amount: float
    guarantee_type: str
    guarantee_days: int
    guarantee_text: str
    urgency_type: str
    urgency_text: str
    scarcity_count: int
    value_stack_items: list[OfferValueStackItem]
    cta_text: str
    cta_subtext: str
    is_active: bool
    is_public: bool
    public_slug: str
    require_email: bool
    require_phone: bool
    require_name: bool

    def to_offer_values(self, workspace_id: uuid.UUID) -> dict[str, object]:
        """Return values accepted by the Offer model constructor."""
        return {
            "workspace_id": workspace_id,
            "name": self.name,
            "description": self.description,
            "discount_type": self.discount_type,
            "discount_value": self.discount_value,
            "terms": self.terms,
            "headline": self.headline,
            "subheadline": self.subheadline,
            "regular_price": self.regular_price,
            "offer_price": self.offer_price,
            "savings_amount": self.savings_amount,
            "guarantee_type": self.guarantee_type,
            "guarantee_days": self.guarantee_days,
            "guarantee_text": self.guarantee_text,
            "urgency_type": self.urgency_type,
            "urgency_text": self.urgency_text,
            "scarcity_count": self.scarcity_count,
            "value_stack_items": self.value_stack_items,
            "cta_text": self.cta_text,
            "cta_subtext": self.cta_subtext,
            "is_active": self.is_active,
            "is_public": self.is_public,
            "public_slug": self.public_slug,
            "require_email": self.require_email,
            "require_phone": self.require_phone,
            "require_name": self.require_name,
        }


PRESTYJ_BATCH_VIDEO_ADS_TEMPLATE = OfferTemplate(
    name="Prestyj Batch Video Ads",
    description=(
        "A reusable paid video ads offer for brands that need high-volume short-form creative "
        "without a drawn-out production cycle. One recording session turns into 100, 300, 500, "
        "or 1,000 ready-to-test ad variations delivered in 1-2 days."
    ),
    discount_type="fixed",
    discount_value=0.0,
    terms=(
        "Built for paid video ads. Includes one recording session and batch production of "
        "selected ad volume. Delivery target is 1-2 days after the recording session and "
        "receipt of required brand assets. Pricing tiers: 100 ads for $497, 300 ads for "
        "$1,497, 500 ads for $2,497, or 1,000 ads for $3,997."
    ),
    headline="Get 100-1,000 Paid Video Ads From One Recording Session",
    subheadline=(
        "Prestyj turns one focused recording session into a complete batch of paid-video ad "
        "creative in 1-2 days, so you can test more hooks, angles, and offers faster."
    ),
    regular_price=3997.0,
    offer_price=497.0,
    savings_amount=0.0,
    guarantee_type="satisfaction",
    guarantee_days=0,
    guarantee_text=(
        "Creative is produced from one approved recording session according to the selected "
        "package scope and delivered for paid-ad testing."
    ),
    urgency_type="limited_quantity",
    urgency_text="1-2 day delivery windows depend on recording-session availability.",
    scarcity_count=1,
    value_stack_items=[
        {
            "name": "100 paid video ads",
            "description": "Entry batch for rapid creative testing from one recording session.",
            "value": 497.0,
            "included": True,
        },
        {
            "name": "300 paid video ads",
            "description": "Expanded creative batch for more hooks, formats, and audience angles.",
            "value": 1497.0,
            "included": True,
        },
        {
            "name": "500 paid video ads",
            "description": "Large paid-social testing library for scaling winning messages.",
            "value": 2497.0,
            "included": True,
        },
        {
            "name": "1,000 paid video ads",
            "description": "Maximum-volume creative batch for aggressive paid acquisition testing.",
            "value": 3997.0,
            "included": True,
        },
        {
            "name": "One recording session",
            "description": (
                "Capture the core source material once, then repurpose it into batch ad creative."
            ),
            "value": 0.0,
            "included": True,
        },
        {
            "name": "1-2 day delivery",
            "description": (
                "Fast turnaround after the recording session and required assets are complete."
            ),
            "value": 0.0,
            "included": True,
        },
    ],
    cta_text="Book Your Batch",
    cta_subtext="Choose 100, 300, 500, or 1,000 paid video ads.",
    is_active=True,
    is_public=True,
    public_slug=PRESTYJ_BATCH_VIDEO_ADS_PUBLIC_SLUG,
    require_email=True,
    require_phone=True,
    require_name=True,
)


async def upsert_prestyj_batch_video_ads_offer(
    db: AsyncSession,
    workspace_id: uuid.UUID = DEFAULT_WORKSPACE_ID,
) -> Offer:
    """Create or update the Prestyj Batch Video Ads offer without deleting data."""
    template_values = PRESTYJ_BATCH_VIDEO_ADS_TEMPLATE.to_offer_values(workspace_id)
    result = await db.execute(
        select(Offer).where(
            Offer.workspace_id == workspace_id,
            Offer.public_slug == PRESTYJ_BATCH_VIDEO_ADS_PUBLIC_SLUG,
        )
    )
    offer = result.scalar_one_or_none()

    if offer is None:
        offer = Offer(**template_values)
        db.add(offer)
    else:
        for field, value in template_values.items():
            setattr(offer, field, value)

    await db.commit()
    await db.refresh(offer)
    return offer


async def seed_prestyj_batch_video_ads_offer(workspace_id: uuid.UUID) -> Offer:
    """Open a database session and upsert the Prestyj offer template."""
    async with AsyncSessionLocal() as db:
        return await upsert_prestyj_batch_video_ads_offer(db, workspace_id)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Safely upsert Prestyj's reusable Batch Video Ads offer template."
    )
    parser.add_argument(
        "--workspace-id",
        type=uuid.UUID,
        default=DEFAULT_WORKSPACE_ID,
        help=(
            "Workspace UUID to seed into. Defaults to DEFAULT_WORKSPACE_ID env var or app "
            "default."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Run the seed script from the command line."""
    args = parse_args()
    offer = asyncio.run(seed_prestyj_batch_video_ads_offer(args.workspace_id))
    print(
        "Seeded Prestyj Batch Video Ads offer "
        f"(id={offer.id}, workspace_id={offer.workspace_id}, slug={offer.public_slug})"
    )


if __name__ == "__main__":
    main()
