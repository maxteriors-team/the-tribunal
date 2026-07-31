"""Season windows and lead time — the calendar maths behind pre-booking.

Two questions, both pure functions over dates so they can be exercised without a
database and answered identically by the API, the worker and the wizard UI:

1. **When is the work actually happening?** The operator picks months ("March
   through May"), not dates, and a season is allowed to wrap the new year
   (November through February). :func:`resolve_season_window` turns that into a
   concrete ``[start, end]`` pair.
2. **Is it too late to run this campaign?** Selling a spring season in March is
   not pre-booking, it is scrambling. :func:`assess_lead_time` grades the gap
   between launch and season start so the UI can say so *before* the operator
   spends a month of SMS on it.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from typing import Literal

# The gap that makes pre-booking work. A January–March season built in September
# has ~120 days of runway: enough for a first send, two follow-ups, and the
# customer's own "let me talk to my wife" cycle, while the money is still being
# spent on Christmas rather than on somebody else's spring special.
AMPLE_LEAD_DAYS = 90

# Below this the campaign can still land, but the discount is now buying urgency
# rather than planning, and the crew has little room to shape the calendar.
TIGHT_LEAD_DAYS = 30

LeadTimeStatus = Literal["ample", "tight", "late"]


@dataclass(frozen=True, slots=True)
class SeasonWindow:
    """The concrete calendar window a pre-booking campaign is selling into."""

    start: date
    end: date

    @property
    def days(self) -> int:
        """Inclusive length of the window in days."""
        return (self.end - self.start).days + 1


@dataclass(frozen=True, slots=True)
class LeadTime:
    """How far ahead of the season a campaign is launching."""

    days: int
    status: LeadTimeStatus
    message: str

    @property
    def weeks(self) -> int:
        """Whole weeks of runway (negative once the season has started)."""
        return int(self.days / 7)


def month_name(month: int) -> str:
    """Return the English month name for 1-12, for operator-facing copy."""
    _validate_month(month)
    return (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )[month - 1]


def resolve_season_window(*, start_month: int, end_month: int, year: int) -> SeasonWindow:
    """Resolve a month range plus a start year into concrete dates.

    ``year`` is the year the window *starts* in. A season whose end month is
    earlier than its start month wraps into the following year — holiday lighting
    sold as "November through January" is one season, not two — which is why the
    end year is derived here rather than stored. The end date is the last day of
    ``end_month``, so a February season is 28 or 29 days without the caller
    knowing which.
    """
    _validate_month(start_month)
    _validate_month(end_month)

    end_year = year if end_month >= start_month else year + 1
    return SeasonWindow(
        start=date(year, start_month, 1),
        end=date(end_year, end_month, monthrange(end_year, end_month)[1]),
    )


def describe_season(*, start_month: int, end_month: int, year: int) -> str:
    """Human label for a season window, e.g. ``"March–May 2027"``."""
    window = resolve_season_window(start_month=start_month, end_month=end_month, year=year)
    if start_month == end_month:
        return f"{month_name(start_month)} {window.start.year}"
    if window.start.year == window.end.year:
        return f"{month_name(start_month)}–{month_name(end_month)} {window.start.year}"
    return (
        f"{month_name(start_month)} {window.start.year}–{month_name(end_month)} {window.end.year}"
    )


def lead_time_days(*, launch_on: date, season_start: date) -> int:
    """Days between a campaign launching and the season opening (may be negative)."""
    return (season_start - launch_on).days


def assess_lead_time(days: int) -> LeadTime:
    """Grade a lead time so the UI can warn before the money is spent.

    ``late`` is not an error — an operator may deliberately run a mid-season
    fill-the-calendar push — but it is never what pre-booking is *for*, so it is
    labelled rather than silently accepted.
    """
    if days >= AMPLE_LEAD_DAYS:
        return LeadTime(
            days=days,
            status="ample",
            message=(
                f"{days // 30} month(s) of runway before the season opens — "
                "the right time to pre-sell."
            ),
        )
    if days >= TIGHT_LEAD_DAYS:
        return LeadTime(
            days=days,
            status="tight",
            message=(
                f"Only {days} days before the season opens. Still workable, but "
                f"{AMPLE_LEAD_DAYS}+ days gives follow-ups room to land."
            ),
        )
    if days >= 0:
        return LeadTime(
            days=days,
            status="late",
            message=(
                f"The season opens in {days} days. This is a fill-the-calendar "
                "push, not a pre-booking campaign — build next season's now."
            ),
        )
    return LeadTime(
        days=days,
        status="late",
        message=(
            f"The season started {abs(days)} days ago. Point this at the next season instead."
        ),
    )


def next_season_year(*, start_month: int, today: date) -> int:
    """The next year in which ``start_month`` is still ahead of ``today``.

    Used to prefill the wizard: an operator opening the form in September for a
    January season means *next* January, and making them work that out is how a
    campaign ends up pointed at a season that already happened.
    """
    _validate_month(start_month)
    return today.year if start_month > today.month else today.year + 1


def _validate_month(month: int) -> None:
    if not 1 <= month <= 12:
        raise ValueError(f"Month must be between 1 and 12, got {month}")
