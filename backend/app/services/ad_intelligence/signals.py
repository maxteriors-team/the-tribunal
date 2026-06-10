"""The "consistent but not testing" signal engine.

Given an advertiser's creatives over a rolling window, compute the metrics that
identify the ICP — advertisers who run ads **consistently** but **do not
iterate** their creatives:

* ``longest_running_active_days`` — max(now - delivery_start) over active ads.
  High = a stale winner they never refresh.
* ``active_creative_count`` / ``distinct_creative_count`` — deduped by
  ``creative_hash``. Low = few creatives.
* ``creative_refresh_rate`` — distinct new creatives introduced per 30 days.
  Low = no testing.
* ``continuity_score`` — fraction of weeks in the window with >= 1 active ad.
  High = a consistent spender.
* ``opportunity_score`` — a weighted 0..100 blend that rewards
  ``high continuity + long longest-run + low distinct-creative + low refresh``,
  with a human-readable ``reasons[]`` evidence list.

Also selects a ``representative_creative`` — the specific ad we'd reference in
outreach ("saw your ad running since March…") so messaging is concrete, not
generic.

This is a **pure** module: it takes lightweight creative facts (not ORM rows)
and returns a dataclass. :func:`compute_signals_for_advertiser` adapts ORM rows
and writes the result back onto the ``AdAdvertiser``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.ad_advertiser import AdAdvertiser
    from app.models.ad_creative import AdCreative

_DAY = timedelta(days=1)
_WEEK = timedelta(days=7)


@dataclass(slots=True, frozen=True)
class CreativeFact:
    """Lightweight, ORM-free view of one observed ad for signal math."""

    ad_external_id: str
    creative_hash: str | None
    media_type: str
    is_active: bool
    delivery_start: datetime | None
    delivery_stop: datetime | None
    platforms: tuple[str, ...] = ()
    body: str | None = None
    link_caption: str | None = None
    link_url: str | None = None
    snapshot_url: str | None = None


@dataclass(slots=True)
class AdvertiserSignals:
    """Computed signal bundle for one advertiser."""

    signal_window_days: int
    total_ad_count: int
    active_ad_count: int
    distinct_creative_count: int
    active_creative_count: int
    longest_running_active_days: int
    creative_refresh_rate: float
    continuity_score: float
    opportunity_score: int
    platform_spread: list[str] = field(default_factory=list)
    media_mix: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    representative_creative: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# Weights for the opportunity blend (sum to 1.0). Tuned so a consistent,
# long-running, low-diversity, no-refresh advertiser approaches 100.
_W_CONTINUITY = 0.30
_W_LONGEVITY = 0.30
_W_LOW_DIVERSITY = 0.25
_W_LOW_REFRESH = 0.15

# Saturation points for normalizing raw metrics into 0..1 sub-scores.
_LONGEVITY_SATURATION_DAYS = 180  # >= 6 months running == full longevity score
_DIVERSITY_SATURATION = 10  # >= 10 distinct creatives == zero low-diversity score
_REFRESH_SATURATION = 6.0  # >= 6 new creatives / 30d == zero low-refresh score


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_signals(
    creatives: list[CreativeFact],
    *,
    now: datetime | None = None,
    window_days: int = 365,
) -> AdvertiserSignals:
    """Compute the full signal bundle for one advertiser (pure)."""
    now = now or datetime.now(UTC)
    window_start = now - timedelta(days=window_days)

    # Restrict to creatives that overlap the window at all.
    in_window = [c for c in creatives if _overlaps_window(c, window_start, now)]
    active = [c for c in in_window if c.is_active]

    # No ads in window => no signal, no opportunity. Short-circuit so the
    # low-diversity/low-refresh defaults don't manufacture a phantom score.
    if not in_window:
        return AdvertiserSignals(
            signal_window_days=window_days,
            total_ad_count=0,
            active_ad_count=0,
            distinct_creative_count=0,
            active_creative_count=0,
            longest_running_active_days=0,
            creative_refresh_rate=0.0,
            continuity_score=0.0,
            opportunity_score=0,
            platform_spread=[],
            media_mix={},
            reasons=[],
            representative_creative=None,
            extra={"window_start": window_start.isoformat()},
        )

    distinct_hashes = {c.creative_hash for c in in_window if c.creative_hash}
    active_hashes = {c.creative_hash for c in active if c.creative_hash}
    distinct_creative_count = len(distinct_hashes) or len(in_window)
    active_creative_count = len(active_hashes) or len(active)

    longest_running_active_days = _longest_running_active_days(active, now)
    continuity_score = _continuity_score(in_window, window_start, now)
    creative_refresh_rate = _creative_refresh_rate(in_window, window_start, now, window_days)
    platform_spread = _platform_spread(in_window)
    media_mix = _media_mix(in_window)

    opportunity_score, reasons = _score_and_reasons(
        active_ad_count=len(active),
        distinct_creative_count=distinct_creative_count,
        longest_running_active_days=longest_running_active_days,
        continuity_score=continuity_score,
        creative_refresh_rate=creative_refresh_rate,
        media_mix=media_mix,
    )
    representative = _representative_creative(active or in_window, now)

    return AdvertiserSignals(
        signal_window_days=window_days,
        total_ad_count=len(in_window),
        active_ad_count=len(active),
        distinct_creative_count=distinct_creative_count,
        active_creative_count=active_creative_count,
        longest_running_active_days=longest_running_active_days,
        creative_refresh_rate=round(creative_refresh_rate, 3),
        continuity_score=round(continuity_score, 3),
        opportunity_score=opportunity_score,
        platform_spread=platform_spread,
        media_mix=media_mix,
        reasons=reasons,
        representative_creative=representative,
        extra={
            "distinct_creative_hashes": len(distinct_hashes),
            "window_start": window_start.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Metric helpers (pure)
# ---------------------------------------------------------------------------


def _overlaps_window(c: CreativeFact, window_start: datetime, now: datetime) -> bool:
    start = c.delivery_start or window_start
    stop = c.delivery_stop or now
    return stop >= window_start and start <= now


def _longest_running_active_days(active: list[CreativeFact], now: datetime) -> int:
    longest = 0
    for c in active:
        if c.delivery_start is None:
            continue
        days = int((now - c.delivery_start) / _DAY)
        longest = max(longest, days)
    return max(0, longest)


def _continuity_score(
    creatives: list[CreativeFact], window_start: datetime, now: datetime
) -> float:
    """Fraction of weeks in the window that had at least one ad delivering."""
    total_weeks = max(1, int((now - window_start) / _WEEK))
    covered: set[int] = set()
    for c in creatives:
        start = max(c.delivery_start or window_start, window_start)
        stop = min(c.delivery_stop or now, now)
        if stop < start:
            continue
        first_week = int((start - window_start) / _WEEK)
        last_week = int((stop - window_start) / _WEEK)
        covered.update(range(first_week, last_week + 1))
    covered = {w for w in covered if 0 <= w < total_weeks}
    return _clamp01(len(covered) / total_weeks)


def _creative_refresh_rate(
    creatives: list[CreativeFact],
    window_start: datetime,
    now: datetime,
    window_days: int,
) -> float:
    """New distinct creatives introduced per 30 days over the window.

    Counts the first appearance (by delivery start) of each distinct creative
    hash, then divides by the number of 30-day periods in the window.
    """
    first_seen_by_hash: dict[str, datetime] = {}
    for c in creatives:
        key = c.creative_hash or c.ad_external_id
        start = c.delivery_start or window_start
        if key not in first_seen_by_hash or start < first_seen_by_hash[key]:
            first_seen_by_hash[key] = start
    introduced = sum(1 for start in first_seen_by_hash.values() if start >= window_start)
    periods = max(1.0, window_days / 30.0)
    return introduced / periods


def _platform_spread(creatives: list[CreativeFact]) -> list[str]:
    seen: set[str] = set()
    for c in creatives:
        seen.update(p for p in c.platforms if p)
    return sorted(seen)


def _media_mix(creatives: list[CreativeFact]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for c in creatives:
        counter[c.media_type or "unknown"] += 1
    return dict(counter)


def _score_and_reasons(
    *,
    active_ad_count: int,
    distinct_creative_count: int,
    longest_running_active_days: int,
    continuity_score: float,
    creative_refresh_rate: float,
    media_mix: dict[str, int],
) -> tuple[int, list[str]]:
    """Blend metrics into a 0..100 opportunity score + human-readable reasons."""
    # Sub-scores (0..1), each rewarding the ICP direction.
    longevity = _clamp01(longest_running_active_days / _LONGEVITY_SATURATION_DAYS)
    low_diversity = _clamp01(1.0 - (distinct_creative_count - 1) / _DIVERSITY_SATURATION)
    low_refresh = _clamp01(1.0 - creative_refresh_rate / _REFRESH_SATURATION)
    continuity = _clamp01(continuity_score)

    raw = (
        _W_CONTINUITY * continuity
        + _W_LONGEVITY * longevity
        + _W_LOW_DIVERSITY * low_diversity
        + _W_LOW_REFRESH * low_refresh
    )
    # An advertiser with no currently-active ads isn't a live opportunity.
    if active_ad_count == 0:
        raw *= 0.4
    score = int(round(raw * 100))

    reasons: list[str] = []
    if longest_running_active_days > 0:
        reasons.append(
            f"Running the same creative for {longest_running_active_days} days "
            f"(active set: {distinct_creative_count} distinct)."
        )
    if distinct_creative_count <= 3:
        reasons.append(
            f"Only {distinct_creative_count} distinct creative"
            f"{'s' if distinct_creative_count != 1 else ''} — minimal variation."
        )
    if creative_refresh_rate < 1.0:
        reasons.append(
            f"~{creative_refresh_rate:.1f} new creatives per 30 days — little to no testing."
        )
    if continuity >= 0.6:
        reasons.append(
            f"Consistent spender: ads delivering in {int(round(continuity * 100))}% of weeks."
        )
    if media_mix:
        dominant = max(media_mix, key=lambda k: media_mix[k])
        reasons.append(f"Mostly {dominant} creatives.")
    return score, reasons


def _representative_creative(creatives: list[CreativeFact], now: datetime) -> dict[str, Any] | None:
    """Pick the ad to reference in outreach: the longest-running active one.

    Returns a compact, outreach-ready blob (body snippet, link caption, snapshot
    URL, running days) so a message can name a specific ad the prospect runs.
    """
    if not creatives:
        return None

    def _running_days(c: CreativeFact) -> int:
        if c.delivery_start is None:
            return 0
        return int((now - c.delivery_start) / _DAY)

    best = max(creatives, key=_running_days)
    body = (best.body or "").strip()
    snippet = body[:160] + ("…" if len(body) > 160 else "") if body else None
    return {
        "ad_external_id": best.ad_external_id,
        "body_snippet": snippet,
        "link_caption": best.link_caption,
        "link_url": best.link_url,
        "snapshot_url": best.snapshot_url,
        "media_type": best.media_type,
        "running_days": _running_days(best),
        "delivery_start_time": best.delivery_start.isoformat() if best.delivery_start else None,
    }


# ---------------------------------------------------------------------------
# ORM adapter
# ---------------------------------------------------------------------------


def creative_to_fact(creative: AdCreative) -> CreativeFact:
    """Adapt an ``AdCreative`` ORM row into a pure :class:`CreativeFact`."""
    media = creative.media_type.value if creative.media_type is not None else "unknown"
    platforms = tuple(creative.platforms or ())
    return CreativeFact(
        ad_external_id=creative.ad_external_id,
        creative_hash=creative.creative_hash,
        media_type=media,
        is_active=bool(creative.is_active),
        delivery_start=creative.ad_delivery_start_time,
        delivery_stop=creative.ad_delivery_stop_time,
        platforms=platforms,
        body=creative.body,
        link_caption=creative.link_caption,
        link_url=creative.link_url,
        snapshot_url=creative.snapshot_url,
    )


def compute_signals_for_advertiser(
    advertiser: AdAdvertiser,
    creatives: list[AdCreative],
    *,
    now: datetime | None = None,
    window_days: int | None = None,
) -> AdvertiserSignals:
    """Compute signals from ORM rows and write them onto the advertiser.

    Mutates ``advertiser`` in place (signal columns + ``example_creative`` +
    ``reasons``) and returns the bundle. Does not commit.
    """
    window = window_days or advertiser.signal_window_days or 365
    facts = [creative_to_fact(c) for c in creatives]
    bundle = compute_signals(facts, now=now, window_days=window)

    advertiser.signal_window_days = bundle.signal_window_days
    advertiser.total_ad_count = bundle.total_ad_count
    advertiser.active_ad_count = bundle.active_ad_count
    advertiser.distinct_creative_count = bundle.distinct_creative_count
    advertiser.active_creative_count = bundle.active_creative_count
    advertiser.longest_running_active_days = bundle.longest_running_active_days
    advertiser.creative_refresh_rate = bundle.creative_refresh_rate
    advertiser.continuity_score = bundle.continuity_score
    advertiser.opportunity_score = bundle.opportunity_score
    advertiser.platform_spread = bundle.platform_spread
    advertiser.media_mix = bundle.media_mix
    advertiser.reasons = bundle.reasons
    advertiser.example_creative = bundle.representative_creative
    advertiser.is_active = bundle.active_ad_count > 0
    advertiser.signals = {
        "opportunity_score": bundle.opportunity_score,
        "continuity_score": bundle.continuity_score,
        "longest_running_active_days": bundle.longest_running_active_days,
        "distinct_creative_count": bundle.distinct_creative_count,
        "creative_refresh_rate": bundle.creative_refresh_rate,
        **bundle.extra,
    }
    return bundle
