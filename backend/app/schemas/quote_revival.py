"""Workspace settings schemas for the 30/60/90-day unsold-quote revival cadence.

A quote that was issued and went quiet is a warm, already-paid-for lead. This
sequence works it long after the first-14-days post-estimate cadence has ended,
and the ``offset_days`` floor below is the shared rail that keeps the two
sequences from ever messaging the same quote in the same window.
"""

import uuid
from datetime import time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.quote_followup import POST_ESTIMATE_MAX_OFFSET_DAYS

# The post-estimate cadence owns day 0 through day 14 inclusive, so revival may
# not start before day 15. Defaults sit at 30/60/90 with room to tune either way.
REVIVAL_MIN_OFFSET_DAYS = POST_ESTIMATE_MAX_OFFSET_DAYS + 1
REVIVAL_MAX_OFFSET_DAYS = 365

QuoteRevivalChannel = Literal["sms", "email", "call"]


class QuoteRevivalTouchSettings(BaseModel):
    """One revival touch anchored to the quote's issue date."""

    model_config = ConfigDict(extra="forbid")

    offset_days: int = Field(ge=REVIVAL_MIN_OFFSET_DAYS, le=REVIVAL_MAX_OFFSET_DAYS)
    channel: QuoteRevivalChannel
    # Copy for a routine quote. Operators own the wording, so price-validity,
    # seasonal-slot, and financing angles are template choices, not code.
    template_id: uuid.UUID | None = None
    # Optional different approach for quotes at or above the value threshold.
    # Falls back to ``template_id`` when unset.
    high_value_template_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_template_usage(self) -> "QuoteRevivalTouchSettings":
        """Call tasks brief a human; they never render customer-facing copy."""
        if self.channel == "call" and (
            self.template_id is not None or self.high_value_template_id is not None
        ):
            raise ValueError("Call touches cannot have a message template")
        return self


def _default_touches() -> list[QuoteRevivalTouchSettings]:
    """Return the classic 30/60/90 ladder, ending on a human conversation."""
    return [
        QuoteRevivalTouchSettings(offset_days=30, channel="sms"),
        QuoteRevivalTouchSettings(offset_days=60, channel="email"),
        QuoteRevivalTouchSettings(offset_days=90, channel="call"),
    ]


class QuoteRevivalSettings(BaseModel):
    """Validated workspace configuration for unsold-quote revival."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # Quotes at or above this total use the high-value template and are worth a
    # person's time; a $12,000 job should not get the same nudge as a $1,500 one.
    high_value_threshold: float = Field(default=5_000, ge=0, le=100_000_000)
    # Hard ceiling on executed touches per quote, independent of how many are
    # configured. Shrinking this stops a quote mid-ladder instead of retro-firing.
    max_touches: int = Field(default=3, ge=1, le=6)
    quiet_hours_start: time | None = time(20, 0)
    quiet_hours_end: time | None = time(8, 0)
    timezone: str | None = Field(default=None, max_length=100)
    touches: list[QuoteRevivalTouchSettings] = Field(
        default_factory=_default_touches,
        min_length=1,
        max_length=6,
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        """Reject invalid IANA names rather than silently using the wrong local time."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return normalized

    @model_validator(mode="after")
    def validate_cadence(self) -> "QuoteRevivalSettings":
        """Require an ordered ladder and an all-or-nothing quiet window."""
        offsets = [touch.offset_days for touch in self.touches]
        if offsets != sorted(offsets) or len(offsets) != len(set(offsets)):
            raise ValueError("touch offsets must be unique and in ascending order")

        if not any(touch.channel in {"sms", "email"} for touch in self.touches):
            raise ValueError("cadence must include at least one automated touch")

        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("quiet-hours start and end must both be set or both be empty")
        return self


class QuoteRevivalSettingsUpdate(BaseModel):
    """Partial update payload for unsold-quote revival settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    high_value_threshold: float | None = Field(default=None, ge=0, le=100_000_000)
    max_touches: int | None = Field(default=None, ge=1, le=6)
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    timezone: str | None = Field(default=None, max_length=100)
    touches: list[QuoteRevivalTouchSettings] | None = Field(
        default=None,
        min_length=1,
        max_length=6,
    )
