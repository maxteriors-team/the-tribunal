"""Schemas for speed-to-lead SLA settings, metrics, and the public proof badge."""

from pydantic import BaseModel, Field

from app.services.sla.speed_to_lead import (
    DEFAULT_BADGE_WINDOW_DAYS,
    DEFAULT_SLA_SECONDS,
)


class SpeedToLeadSettingsResponse(BaseModel):
    """Per-workspace speed-to-lead SLA configuration."""

    enabled: bool = True
    sla_seconds: int = DEFAULT_SLA_SECONDS
    alert_enabled: bool = True
    badge_enabled: bool = False
    badge_window_days: int = DEFAULT_BADGE_WINDOW_DAYS


class SpeedToLeadSettingsUpdate(BaseModel):
    """Partial update for speed-to-lead SLA configuration."""

    enabled: bool | None = None
    sla_seconds: int | None = Field(default=None, ge=5, le=3600)
    alert_enabled: bool | None = None
    badge_enabled: bool | None = None
    badge_window_days: int | None = Field(default=None, ge=1, le=365)


class SpeedToLeadMetrics(BaseModel):
    """First-response SLA rollup over the recent window (operator-facing)."""

    window_days: int
    sla_seconds: int
    leads_measured: int
    within_sla: int
    pct_within_sla: float | None
    avg_response_seconds: int | None
    median_response_seconds: int | None
    fastest_response_seconds: int | None


class SpeedToLeadProofResponse(BaseModel):
    """Public, origin-validated proof badge for the lead-form widget."""

    enabled: bool  # False when the badge is off or the sample is too small
    sla_seconds: int
    window_days: int
    leads_measured: int
    pct_within_sla: float | None
    median_response_seconds: int | None
    headline: str | None  # e.g. "98.7% of leads answered in under 60s"


class MissedCallTextbackSettingsResponse(BaseModel):
    """Per-workspace missed-call text-back configuration."""

    enabled: bool = False
    template: str = "Sorry we missed you — want me to book you in?"
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str | None = None


class MissedCallTextbackSettingsUpdate(BaseModel):
    """Partial update for missed-call text-back configuration."""

    enabled: bool | None = None
    template: str | None = Field(default=None, max_length=1000)
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str | None = None
