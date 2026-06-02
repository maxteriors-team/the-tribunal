"""Tests for the Prestyj Batch Video Ads offer seed script."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.offer import Offer
from scripts.demo.seed_prestyj_batch_video_ads_offer import (
    PRESTYJ_BATCH_VIDEO_ADS_PUBLIC_SLUG,
    PRESTYJ_BATCH_VIDEO_ADS_TEMPLATE,
    upsert_prestyj_batch_video_ads_offer,
)


class ScalarResult:
    """Minimal SQLAlchemy scalar result test double."""

    def __init__(self, offer: Offer | None) -> None:
        self.offer = offer

    def scalar_one_or_none(self) -> Offer | None:
        return self.offer


@pytest.mark.asyncio
async def test_upsert_creates_prestyj_batch_video_ads_offer() -> None:
    """Seed creates the public Prestyj offer when it does not exist."""
    workspace_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=ScalarResult(None))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    offer = await upsert_prestyj_batch_video_ads_offer(db, workspace_id)

    db.add.assert_called_once_with(offer)
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(offer)
    assert offer.workspace_id == workspace_id
    assert offer.name == "Prestyj Batch Video Ads"
    assert offer.public_slug == PRESTYJ_BATCH_VIDEO_ADS_PUBLIC_SLUG
    assert offer.is_public is True
    assert offer.require_email is True
    assert offer.require_phone is True
    assert offer.require_name is True
    assert offer.offer_price == 497.0
    assert offer.regular_price == 3997.0
    assert offer.cta_text == "Book Your Batch"
    assert "100 ads for $497" in offer.terms
    assert "1-2 days" in offer.terms
    assert offer.value_stack_items == PRESTYJ_BATCH_VIDEO_ADS_TEMPLATE.value_stack_items


@pytest.mark.asyncio
async def test_upsert_updates_existing_offer_without_adding_duplicate() -> None:
    """Seed updates the matching offer by slug instead of creating a duplicate."""
    workspace_id = uuid.uuid4()
    existing_offer = Offer(
        workspace_id=workspace_id,
        name="Old Name",
        public_slug=PRESTYJ_BATCH_VIDEO_ADS_PUBLIC_SLUG,
        discount_type="percentage",
        discount_value=10.0,
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=ScalarResult(existing_offer))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    offer = await upsert_prestyj_batch_video_ads_offer(db, workspace_id)

    db.add.assert_not_called()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(existing_offer)
    assert offer is existing_offer
    assert offer.name == "Prestyj Batch Video Ads"
    assert offer.discount_type == "fixed"
    assert offer.discount_value == 0.0
    assert offer.headline == "Get 100-1,000 Paid Video Ads From One Recording Session"
    assert offer.value_stack_items is not None
    tier_values = {item["name"]: item["value"] for item in offer.value_stack_items}
    assert tier_values == {
        "100 paid video ads": 497.0,
        "300 paid video ads": 1497.0,
        "500 paid video ads": 2497.0,
        "1,000 paid video ads": 3997.0,
        "One recording session": 0.0,
        "1-2 day delivery": 0.0,
    }


def test_template_contains_required_batch_video_ads_terms() -> None:
    """Template documents the package constraints requested for Prestyj."""
    template_values: dict[str, Any] = PRESTYJ_BATCH_VIDEO_ADS_TEMPLATE.to_offer_values(
        uuid.UUID("ba0e0e99-c7c9-45ec-9625-567d54d6e9c2")
    )

    searchable_text = " ".join(
        str(value) for value in template_values.values() if isinstance(value, str)
    )
    assert "paid video ads" in searchable_text.lower()
    assert "one recording session" in searchable_text.lower()
    assert "1-2 day" in searchable_text.lower()
    assert "100 ads for $497" in searchable_text
    assert "300 ads for $1,497" in searchable_text
    assert "500 ads for $2,497" in searchable_text
    assert "1,000 ads for $3,997" in searchable_text
