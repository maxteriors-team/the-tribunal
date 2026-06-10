"""Unit tests for the ad-signal engine over fixture timelines.

These pin the ICP semantics: a consistent, long-running, low-diversity, no-
refresh advertiser scores high; a prolific tester scores low; the human-
readable reasons + representative creative are populated for outreach.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.ad_intelligence.signals import (
    CreativeFact,
    compute_signals,
)

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _fact(
    ad_id: str,
    *,
    hash_: str,
    start_days_ago: int,
    stop_days_ago: int | None = None,
    active: bool = True,
    media: str = "image",
    body: str = "Same old ad",
    platforms: tuple[str, ...] = ("FACEBOOK",),
) -> CreativeFact:
    return CreativeFact(
        ad_external_id=ad_id,
        creative_hash=hash_,
        media_type=media,
        is_active=active,
        delivery_start=NOW - timedelta(days=start_days_ago),
        delivery_stop=(NOW - timedelta(days=stop_days_ago)) if stop_days_ago is not None else None,
        platforms=platforms,
        body=body,
        link_caption="acme.example",
        link_url="https://acme.example",
        snapshot_url="https://facebook.com/ads/render?id=" + ad_id,
    )


def test_ideal_icp_scores_high() -> None:
    # One creative running continuously for ~210 days, still active, no refresh.
    facts = [_fact("1", hash_="h1", start_days_ago=210, active=True)]
    sig = compute_signals(facts, now=NOW, window_days=365)

    assert sig.longest_running_active_days == 210
    assert sig.distinct_creative_count == 1
    assert sig.active_ad_count == 1
    assert sig.creative_refresh_rate < 0.2
    assert sig.opportunity_score >= 70
    assert any("Running the same creative" in r for r in sig.reasons)
    # Representative creative is the long-runner, ready for outreach.
    assert sig.representative_creative is not None
    assert sig.representative_creative["ad_external_id"] == "1"
    assert sig.representative_creative["running_days"] == 210


def test_prolific_tester_scores_low() -> None:
    # 24 distinct creatives, each fresh in the last ~60 days => lots of testing.
    facts = [
        _fact(str(i), hash_=f"h{i}", start_days_ago=60 - (i * 2), active=True, body=f"variant {i}")
        for i in range(24)
    ]
    sig = compute_signals(facts, now=NOW, window_days=365)

    assert sig.distinct_creative_count == 24
    assert sig.creative_refresh_rate > 1.5
    # Heavy testers are not our buyer — they should not look like an opportunity.
    assert sig.opportunity_score < 50


def test_inactive_advertiser_is_dampened() -> None:
    # A long-running creative that has since stopped: not a live opportunity.
    facts = [_fact("1", hash_="h1", start_days_ago=200, stop_days_ago=30, active=False)]
    sig = compute_signals(facts, now=NOW, window_days=365)
    assert sig.active_ad_count == 0
    assert sig.longest_running_active_days == 0
    # Dampened relative to the same creative still active.
    assert sig.opportunity_score < 60


def test_continuity_reflects_week_coverage() -> None:
    # Continuous single ad over a 28-day window => ~full continuity.
    facts = [_fact("1", hash_="h1", start_days_ago=28, active=True)]
    sig = compute_signals(facts, now=NOW, window_days=28)
    assert sig.continuity_score >= 0.9

    # A 1-day blip in a 365-day window => near-zero continuity.
    blip = [_fact("1", hash_="h1", start_days_ago=10, stop_days_ago=9, active=False)]
    sig2 = compute_signals(blip, now=NOW, window_days=365)
    assert sig2.continuity_score < 0.1


def test_distinct_dedupes_by_hash() -> None:
    # Same creative hash re-published under three ad ids = one distinct creative.
    facts = [
        _fact("1", hash_="same", start_days_ago=120, active=True),
        _fact("2", hash_="same", start_days_ago=100, active=True),
        _fact("3", hash_="same", start_days_ago=80, active=True),
    ]
    sig = compute_signals(facts, now=NOW, window_days=365)
    assert sig.distinct_creative_count == 1
    assert sig.active_ad_count == 3


def test_media_mix_and_platform_spread() -> None:
    facts = [
        _fact("1", hash_="h1", start_days_ago=100, media="video", platforms=("FACEBOOK",)),
        _fact("2", hash_="h2", start_days_ago=90, media="image", platforms=("INSTAGRAM",)),
        _fact(
            "3", hash_="h3", start_days_ago=80, media="video", platforms=("FACEBOOK", "MESSENGER")
        ),
    ]
    sig = compute_signals(facts, now=NOW, window_days=365)
    assert sig.media_mix == {"video": 2, "image": 1}
    assert sig.platform_spread == ["FACEBOOK", "INSTAGRAM", "MESSENGER"]


def test_empty_advertiser_is_safe() -> None:
    sig = compute_signals([], now=NOW, window_days=365)
    assert sig.opportunity_score == 0
    assert sig.representative_creative is None
    assert sig.total_ad_count == 0
