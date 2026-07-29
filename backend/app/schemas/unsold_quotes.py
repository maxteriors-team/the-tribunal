"""Per-workspace unsold-quote follow-up schemas.

A quote that was sent and went quiet is the warmest lead a home-services
business owns: the site visit is paid for, the scope is agreed, and the only
thing missing is a decision. Nothing in the platform worked those quotes, so
they aged into ``expired`` and the revenue evaporated silently.

This config is the operator-owned half of
:mod:`app.workers.unsold_quote_worker`: which days after ``issue_date`` a quote
gets a nudge, what each nudge leads with, and where the line sits between a
"$1,500 job" message and a "$12,000 project" message. Stored as a JSONB blob
under ``workspace.settings["unsold_quotes"]`` and read through
:mod:`app.services.quotes.unsold_quote_config`, exactly like the pricing config
and the attach rules.

Read leniently (a hand-edited blob never 500s a settings read); write validated
(offsets are sorted/de-duplicated and clock strings are checked at the edge).
Ships **off**: this sends real SMS to real past customers, so an operator turns
it on deliberately rather than discovering it in their sent log.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.compliance.quiet_hours import parse_clock

# What a touch leads with. Three hooks, because these are the three reasons a
# quiet quote actually re-opens in the trades:
#   price_validity - the number on the estimate will not hold forever
#   seasonal       - the calendar is filling and the work is weather-bound
#   financing      - the total, not the job, was the objection
UnsoldQuoteHook = Literal["price_validity", "seasonal", "financing"]

# Which message a quote gets. A $12k project and a $1.5k job are different
# conversations: the small one wants convenience, the large one wants payment
# terms and reassurance, so the copy is chosen per band.
UnsoldQuoteBand = Literal["standard", "high_value"]

# Hard ceiling on configured touches. Beyond a handful of nudges an unsold
# quote is not warm any more, it is harassment — and TCPA exposure.
MAX_TOUCHES = 6

# Latest offset an operator may configure. Two years past issue is well beyond
# the point where the quoted price means anything.
MAX_DAY_OFFSET = 730

DEFAULT_DAY_OFFSETS = (30, 60, 90)
DEFAULT_HOOKS: tuple[UnsoldQuoteHook, ...] = ("price_validity", "seasonal", "financing")

# Value (in the quote's currency) at or above which a quote gets the
# high-value copy. Sized for exterior trades, where a whole-house or
# multi-service job clears five figures and a one-off clean does not.
DEFAULT_VALUE_THRESHOLD = 5000.0

# Quiet hours are on by default and generous. An unsold-quote nudge is never
# urgent, so there is no version of this worker that should text someone at
# 06:40 because a workspace forgot to configure a window.
DEFAULT_QUIET_HOURS_START = "21:00"
DEFAULT_QUIET_HOURS_END = "08:00"


# Fallback copy, used when a touch names no :class:`~app.models.message_template.MessageTemplate`
# (or names one that has since been deleted). Placeholders are rendered by the
# worker; an unknown placeholder is left as-is rather than blanking the message.
DEFAULT_TEMPLATE_BODIES: dict[tuple[str, str], str] = {
    ("price_validity", "standard"): (
        "Hi {first_name}, your estimate {quote_number} for {quote_total} is still on file. "
        "I can hold that price a little longer if you want to lock it in — want me to get "
        "you on the schedule? {quote_link}"
    ),
    ("price_validity", "high_value"): (
        "Hi {first_name}, checking in on your {quote_total} estimate ({quote_number}). "
        "Material pricing moves on projects this size, so I'd rather hold your number than "
        "re-quote it. Happy to walk through the scope or trim it — what works? {quote_link}"
    ),
    ("seasonal", "standard"): (
        "Hi {first_name}, we're booking up and I still have your estimate {quote_number} "
        "at {quote_total}. Want me to save you one of the remaining slots? {quote_link}"
    ),
    ("seasonal", "high_value"): (
        "Hi {first_name}, we're scheduling the larger jobs now while there's still room in "
        "the season. Your {quote_total} estimate ({quote_number}) is ready to go — want me "
        "to pencil in a start week? {quote_link}"
    ),
    ("financing", "standard"): (
        "Hi {first_name}, quick one on estimate {quote_number}: we can split it into monthly "
        "payments if the total was the sticking point. Want me to send the options? "
        "{quote_link}"
    ),
    ("financing", "high_value"): (
        "Hi {first_name}, on a {quote_total} project most customers finance rather than pay "
        "up front — approval takes a couple of minutes and turns it into a monthly number. "
        "Want me to send it over? {quote_link}"
    ),
}


def default_template_body(hook: str, band: str) -> str:
    """Return the built-in copy for ``hook``/``band``.

    Falls back to the standard-band copy, then to the price-validity hook, so a
    config carrying a hook this build does not know still sends something
    sensible instead of an empty text.
    """
    return (
        DEFAULT_TEMPLATE_BODIES.get((hook, band))
        or DEFAULT_TEMPLATE_BODIES.get((hook, "standard"))
        or DEFAULT_TEMPLATE_BODIES[("price_validity", "standard")]
    )


def _validated_clock(value: str | None) -> str | None:
    """Reject an unparseable clock string at the write edge."""
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if parse_clock(trimmed) is None:
        msg = f"invalid time {value!r}; expected HH:MM"
        raise ValueError(msg)
    return trimmed


def _clean_name(value: str | None) -> str | None:
    """Trim a template name; blank means "use the built-in copy"."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


class UnsoldQuoteTouch(BaseModel):
    """One nudge in the sequence: when it fires and what it leads with.

    Templates are named, not inlined, so the copy lives in the existing
    :class:`~app.models.message_template.MessageTemplate` library the operator
    already edits and tests. A name that no longer resolves falls back to the
    built-in copy for the hook rather than dropping the touch — a deleted
    template must not silently switch the sequence off.
    """

    model_config = ConfigDict(extra="ignore")

    # Days after the quote's ``issue_date`` this touch becomes due.
    day_offset: int = Field(ge=1, le=MAX_DAY_OFFSET)
    hook: UnsoldQuoteHook = "price_validity"
    # ``MessageTemplate.name`` used for quotes below ``value_threshold``.
    template_name: str | None = Field(default=None, max_length=255)
    # ``MessageTemplate.name`` used at or above ``value_threshold``.
    high_value_template_name: str | None = Field(default=None, max_length=255)

    @field_validator("template_name", "high_value_template_name")
    @classmethod
    def _trim_names(cls, value: str | None) -> str | None:
        return _clean_name(value)


def _default_touches() -> list[UnsoldQuoteTouch]:
    """The 30/60/90 sequence, each day leading with a different reason to reply."""
    return [
        UnsoldQuoteTouch(day_offset=offset, hook=hook)
        for offset, hook in zip(DEFAULT_DAY_OFFSETS, DEFAULT_HOOKS, strict=True)
    ]


def _normalize_touches(values: list[UnsoldQuoteTouch]) -> list[UnsoldQuoteTouch]:
    """Sort by day, drop duplicate days, and cap the sequence length.

    Cleaning rather than rejecting: a mis-ordered or duplicated day is a slip in
    the settings UI, not a reason to refuse the whole config. Order is the
    load-bearing property — the worker walks the list in sequence, so an
    unsorted list would fire day 90 before day 30.
    """
    cleaned: list[UnsoldQuoteTouch] = []
    seen: set[int] = set()
    for touch in sorted(values, key=lambda item: item.day_offset):
        if touch.day_offset in seen:
            continue
        seen.add(touch.day_offset)
        cleaned.append(touch)
    return cleaned[:MAX_TOUCHES]


class UnsoldQuoteSettings(BaseModel):
    """The full unsold-quote follow-up config for a workspace (read view, lenient)."""

    model_config = ConfigDict(extra="ignore")

    # Off by default: this texts real past customers.
    enabled: bool = False
    touches: list[UnsoldQuoteTouch] = Field(default_factory=_default_touches)
    # Stop after this many touches even when more are configured. Separate from
    # the list so an operator can shorten the sequence for a season without
    # losing the day-90 copy they wrote.
    max_touches: int = Field(default=len(DEFAULT_DAY_OFFSETS), ge=0, le=MAX_TOUCHES)
    # At or above this quote total, the high-value copy is used.
    value_threshold: float = Field(default=DEFAULT_VALUE_THRESHOLD, ge=0)
    quiet_hours_start: str | None = DEFAULT_QUIET_HOURS_START
    quiet_hours_end: str | None = DEFAULT_QUIET_HOURS_END
    # IANA zone for the quiet-hours window; falls back to the workspace timezone.
    timezone: str | None = None

    @field_validator("touches")
    @classmethod
    def _clean_touches(cls, values: list[UnsoldQuoteTouch]) -> list[UnsoldQuoteTouch]:
        return _normalize_touches(values)

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def _clean_clock(cls, value: str | None) -> str | None:
        return _validated_clock(value)

    def active_touches(self) -> list[UnsoldQuoteTouch]:
        """Return the touches that may actually fire, in cadence order."""
        return self.touches[: self.max_touches]

    @property
    def day_offsets(self) -> list[int]:
        """Days after ``issue_date`` at which each active touch becomes due."""
        return [touch.day_offset for touch in self.active_touches()]


class UnsoldQuoteSettingsUpdate(BaseModel):
    """Partial update of the unsold-quote config (shallow top-level merge).

    Every block is optional; only provided keys are written, so flipping
    ``enabled`` never clobbers the cadence. A provided ``touches`` list replaces
    the whole list, matching how the pricing config writes blocks wholesale.
    """

    enabled: bool | None = None
    touches: list[UnsoldQuoteTouch] | None = None
    max_touches: int | None = Field(default=None, ge=0, le=MAX_TOUCHES)
    value_threshold: float | None = Field(default=None, ge=0)
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str | None = None

    @field_validator("touches")
    @classmethod
    def _clean_touches(cls, values: list[UnsoldQuoteTouch] | None) -> list[UnsoldQuoteTouch] | None:
        return None if values is None else _normalize_touches(values)

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def _clean_clock(cls, value: str | None) -> str | None:
        return _validated_clock(value)
