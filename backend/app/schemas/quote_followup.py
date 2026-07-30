"""Workspace settings schemas for the first-14-days quote follow-up cadence."""

import uuid
from datetime import time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

POST_ESTIMATE_MAX_OFFSET_DAYS = 14
QuoteFollowupChannel = Literal["sms", "email", "call"]


class QuoteFollowupTouchSettings(BaseModel):
    """One touch anchored to the quote's first ``sent_at`` timestamp."""

    model_config = ConfigDict(extra="forbid")

    offset_days: int = Field(ge=0, le=POST_ESTIMATE_MAX_OFFSET_DAYS)
    channel: QuoteFollowupChannel
    template_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_template_usage(self) -> "QuoteFollowupTouchSettings":
        """Call tasks do not render customer-facing message templates."""
        if self.channel == "call" and self.template_id is not None:
            raise ValueError("Call touches cannot have a message template")
        return self


def _default_touches() -> list[QuoteFollowupTouchSettings]:
    """Return a safe, mixed-channel cadence that remains disabled until configured."""
    return [
        QuoteFollowupTouchSettings(offset_days=1, channel="sms"),
        QuoteFollowupTouchSettings(offset_days=3, channel="call"),
        QuoteFollowupTouchSettings(offset_days=7, channel="email"),
        QuoteFollowupTouchSettings(offset_days=14, channel="sms"),
    ]


class QuoteFollowupSettings(BaseModel):
    """Validated workspace configuration for post-estimate follow-up."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    high_value_threshold: float = Field(default=10_000, ge=0, le=100_000_000)
    quiet_hours_start: time | None = time(20, 0)
    quiet_hours_end: time | None = time(8, 0)
    timezone: str | None = Field(default=None, max_length=100)
    touches: list[QuoteFollowupTouchSettings] = Field(
        default_factory=_default_touches,
        min_length=3,
        max_length=8,
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
    def validate_cadence(self) -> "QuoteFollowupSettings":
        """Require an ordered, mixed cadence and an all-or-nothing quiet window."""
        offsets = [touch.offset_days for touch in self.touches]
        if offsets != sorted(offsets) or len(offsets) != len(set(offsets)):
            raise ValueError("touch offsets must be unique and in ascending order")

        channels = {touch.channel for touch in self.touches}
        if "call" not in channels:
            raise ValueError("cadence must include at least one human call touch")
        if not channels.intersection({"sms", "email"}):
            raise ValueError("cadence must include at least one automated touch")

        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("quiet-hours start and end must both be set or both be empty")
        return self


class QuoteFollowupSettingsUpdate(BaseModel):
    """Partial update payload for post-estimate follow-up settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    high_value_threshold: float | None = Field(default=None, ge=0, le=100_000_000)
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    timezone: str | None = Field(default=None, max_length=100)
    touches: list[QuoteFollowupTouchSettings] | None = Field(
        default=None,
        min_length=3,
        max_length=8,
    )
