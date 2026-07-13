"""Schemas for speed-to-lead SLA settings, metrics, and the public proof badge."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

from app.services.sla.speed_to_lead import (
    DEFAULT_BADGE_WINDOW_DAYS,
    DEFAULT_SLA_SECONDS,
)


def _validate_clock_str(value: str | None) -> str | None:
    """Validate an ``HH:MM``/``HH:MM:SS`` 24-hour clock string.

    Empty/whitespace normalizes to ``None`` (clears the value). Anything the
    runtime parser can't read is rejected here rather than silently disabling
    quiet hours downstream (which would risk off-hours texting).
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parts = value.split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        msg = "Quiet hours must be in HH:MM or HH:MM:SS 24-hour format"
        raise ValueError(msg)
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        msg = "Quiet hours must be a valid 24-hour clock value"
        raise ValueError(msg)
    return value


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

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def _validate_quiet_hours(cls, v: str | None) -> str | None:
        """Reject clock strings the runtime can't parse; empty clears the value."""
        return _validate_clock_str(v)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str | None) -> str | None:
        """Reject unknown IANA zones that would silently fall back to UTC and
        compute quiet hours against the wrong wall clock. Empty clears it."""
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"Unknown timezone: {v}"
            raise ValueError(msg) from exc
        return v

    @field_validator("template")
    @classmethod
    def _validate_template(cls, v: str | None) -> str | None:
        """A blank template silently no-ops the text-back; reject it early."""
        if v is None:
            return None
        if not v.strip():
            msg = "Message template cannot be empty"
            raise ValueError(msg)
        return v
