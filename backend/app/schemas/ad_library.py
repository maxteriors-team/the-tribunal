"""Pydantic schemas for the Ad Library API.

These drive the ad-library prospecting flow: launch a search (creates a
:class:`~app.models.lead_discovery_job.LeadDiscoveryJob`), configure the ICP
thresholds that select "consistent but not testing" advertisers, and promote a
qualified advertiser into the CRM (prospect -> contact -> optional outreach).
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.ad_advertiser import AdPlatform

# --- ICP thresholds -------------------------------------------------------


class IcpThresholds(BaseModel):
    """Workspace-configurable thresholds that define the ICP.

    The ICP is advertisers who spend **consistently** but **do not iterate**
    their creatives. Crucially this both requires the "stale long-runner"
    signal *and* **excludes prolific testers** — advertisers already running
    many distinct creatives / refreshing often (e.g. 20-100 UGC variations)
    are disqualified, because they already test at scale and are not our buyer.
    """

    # Inclusion floors — must be a consistent, long-running spender.
    min_continuity_score: float = Field(default=0.5, ge=0.0, le=1.0)
    min_longest_running_days: int = Field(default=60, ge=0)
    min_active_ads: int = Field(default=1, ge=0)
    min_opportunity_score: int = Field(default=50, ge=0, le=100)

    # Exclusion ceilings — disqualify advertisers who already test at scale.
    max_distinct_creatives: int = Field(
        default=8,
        ge=1,
        description="Advertisers above this many distinct creatives are excluded "
        "(they already run lots of variations).",
    )
    max_active_creatives: int = Field(
        default=12,
        ge=1,
        description="Hard ceiling on concurrently-active distinct creatives.",
    )
    max_creative_refresh_rate: float = Field(
        default=4.0,
        ge=0.0,
        description="Max new distinct creatives introduced per 30 days; above "
        "this the advertiser is iterating too actively to be a fit.",
    )


class IcpThresholdsUpdate(BaseModel):
    """Partial override of ICP thresholds."""

    min_continuity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    min_longest_running_days: int | None = Field(default=None, ge=0)
    min_active_ads: int | None = Field(default=None, ge=0)
    min_opportunity_score: int | None = Field(default=None, ge=0, le=100)
    max_distinct_creatives: int | None = Field(default=None, ge=1)
    max_active_creatives: int | None = Field(default=None, ge=1)
    max_creative_refresh_rate: float | None = Field(default=None, ge=0.0)


# --- Search ---------------------------------------------------------------


class AdLibrarySearchRequest(BaseModel):
    """Launch an ad-library search.

    Provide either ``search_terms`` (keyword) or a specific page
    (``page_id`` / ``page_name``). The signal window is bounded by
    ``ad_delivery_date_min``/``max`` (effectively required by the Meta API).
    """

    platform: AdPlatform = AdPlatform.META
    country: str = Field(default="US", min_length=2, max_length=2)
    search_terms: str | None = Field(default=None, max_length=512)
    page_id: str | None = Field(default=None, max_length=255)
    page_name: str | None = Field(default=None, max_length=512)
    ad_delivery_date_min: date | None = None
    ad_delivery_date_max: date | None = None
    # Meta supports a server-side ``longest_running`` sort — directly useful.
    sort_by: Literal["longest_running", "most_recent", "default"] = "longest_running"
    max_results: int = Field(default=50, ge=1, le=500)
    # Use the config-gated third-party provider for fuller US coverage.
    use_thirdparty_fallback: bool = False
    mission_id: uuid.UUID | None = None
    # ICP toggles surfaced in the UI; override the workspace defaults for this run.
    icp_thresholds: IcpThresholdsUpdate | None = None

    @model_validator(mode="after")
    def _require_search_target(self) -> "AdLibrarySearchRequest":
        """Require at least one of search_terms / page_id / page_name."""
        if not (self.search_terms or self.page_id or self.page_name):
            raise ValueError("Provide search_terms, page_id, or page_name")
        return self


# --- Monitors (saved searches) -------------------------------------------


class AdMonitorCreate(BaseModel):
    """Create a saved ICP search + recurring re-scan schedule."""

    name: str = Field(min_length=1, max_length=255)
    search: AdLibrarySearchRequest
    icp_thresholds: IcpThresholds = Field(default_factory=IcpThresholds)
    # Re-scan cadence in hours; the monitor worker refreshes active/stop times.
    schedule_interval_hours: int = Field(default=24, ge=1, le=24 * 30)
    is_active: bool = True


class AdMonitorUpdate(BaseModel):
    """Partial update for a saved monitor."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    search: AdLibrarySearchRequest | None = None
    icp_thresholds: IcpThresholdsUpdate | None = None
    schedule_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    is_active: bool | None = None


class AdMonitorResponse(BaseModel):
    """Saved monitor response. Monitors persist inside an OutboundMission's
    ``discovery_config`` so they reuse existing mission rails."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    search: dict[str, Any]
    icp_thresholds: dict[str, Any]
    schedule_interval_hours: int
    is_active: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# --- Promotion ------------------------------------------------------------


class AdvertiserPromoteRequest(BaseModel):
    """Promote a tracked advertiser into the CRM.

    Runs advertiser -> prospect -> contact, carries the ad evidence + the
    representative creative into the contact's ``business_intel`` for
    personalized outreach, and optionally enrolls the new contact in a mission
    sequence.
    """

    mission_id: uuid.UUID | None = None
    enroll_in_sequence: bool = False
    sequence_id: uuid.UUID | None = None
    create_opportunity: bool = False
    extra_tags: list[str] = Field(default_factory=list, max_length=20)


class AdvertiserBulkPromoteRequest(BaseModel):
    """Promote many advertisers at once."""

    advertiser_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    mission_id: uuid.UUID | None = None
    enroll_in_sequence: bool = False
    sequence_id: uuid.UUID | None = None
    create_opportunity: bool = False
    extra_tags: list[str] = Field(default_factory=list, max_length=20)


class AdvertiserPromoteResult(BaseModel):
    """Outcome of promoting one advertiser."""

    advertiser_id: uuid.UUID
    prospect_id: uuid.UUID | None = None
    contact_id: int | None = None
    promoted: bool
    skipped_reason: str | None = None


class AdvertiserBulkPromoteResult(BaseModel):
    """Aggregate outcome of a bulk promote."""

    results: list[AdvertiserPromoteResult]
    promoted_count: int
    skipped_count: int
