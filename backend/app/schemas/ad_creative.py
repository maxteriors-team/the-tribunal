"""Pydantic schemas for ad-library creatives.

An :class:`~app.models.ad_creative.AdCreative` is one ad observed for an
advertiser. These schemas expose the public creative content + delivery window
used both for display (the ad gallery) and for personalized outreach (referring
to a specific ad the prospect is running).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.ad_creative import AdMediaType


class AdCreativeResponse(BaseModel):
    """Response for one observed ad/creative."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    advertiser_id: uuid.UUID
    ad_external_id: str
    creative_hash: str | None
    body: str | None
    title: str | None
    link_caption: str | None
    link_url: str | None
    link_host: str | None
    cta_type: str | None
    snapshot_url: str | None
    media_type: AdMediaType
    platforms: list[str]
    ad_delivery_start_time: datetime | None
    ad_delivery_stop_time: datetime | None
    is_active: bool
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime
