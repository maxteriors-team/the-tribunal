"""Pydantic schemas for ad-library advertisers.

An :class:`~app.models.ad_advertiser.AdAdvertiser` is one advertiser tracked
across a public ad library, carrying the computed "consistent but not testing"
signal. These schemas expose the ranked list (sorted by ``opportunity_score``)
and the detail view (signal breakdown + creatives + traced contact).
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.ad_advertiser import AdPlatform
from app.schemas.ad_creative import AdCreativeResponse


class AdSignalBreakdown(BaseModel):
    """Human-readable breakdown of why an advertiser scored as it did."""

    opportunity_score: int
    signal_window_days: int
    total_ad_count: int
    active_ad_count: int
    distinct_creative_count: int
    active_creative_count: int
    longest_running_active_days: int
    creative_refresh_rate: float
    continuity_score: float
    platform_spread: list[str]
    media_mix: dict[str, int]
    reasons: list[str]
    # The specific ad we'd reference in outreach (body snippet, link caption,
    # snapshot URL, running days). May be ``None`` before signals are computed.
    example_creative: dict[str, Any] | None = None
    signals: dict[str, Any] = {}


class AdAdvertiserResponse(BaseModel):
    """Ranked-list response for one tracked advertiser."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    discovery_job_id: uuid.UUID | None
    prospect_id: uuid.UUID | None
    platform: AdPlatform
    advertiser_key: str
    page_id: str | None
    advertiser_name: str | None
    page_url: str | None
    website_url: str | None
    website_host: str | None
    country_code: str | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    last_scanned_at: datetime | None
    is_active: bool
    signal_window_days: int
    total_ad_count: int
    active_ad_count: int
    distinct_creative_count: int
    active_creative_count: int
    longest_running_active_days: int
    creative_refresh_rate: float
    continuity_score: float
    opportunity_score: int
    platform_spread: list[str]
    media_mix: dict[str, int]
    reasons: list[str]
    example_creative: dict[str, Any] | None
    contact_traced: bool
    created_at: datetime
    updated_at: datetime


class AdAdvertiserDetail(AdAdvertiserResponse):
    """Detail response with creatives, signal breakdown, and traced contact."""

    signals: dict[str, Any]
    provenance: dict[str, Any]
    evidence: list[dict[str, Any]]
    creatives: list[AdCreativeResponse] = []
    signal_breakdown: AdSignalBreakdown | None = None
    # Traced contact (sourced from the linked prospect, never raw PII echoed
    # unless decryptable for the workspace). Populated by the service layer.
    traced_contact: dict[str, Any] | None = None


class PaginatedAdAdvertisers(BaseModel):
    """Paginated advertiser list."""

    items: list[AdAdvertiserResponse]
    total: int
    page: int
    page_size: int
    pages: int
