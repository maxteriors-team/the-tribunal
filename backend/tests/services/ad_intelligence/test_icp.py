"""Tests for the ICP threshold/filter layer.

Pins the core product rule: prolific testers (many distinct creatives / high
refresh) are excluded even if they're consistent long-runners, while a
consistent, low-iteration advertiser qualifies.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.ad_intelligence.icp import IcpProfile, qualifies


def _advertiser(**kwargs) -> SimpleNamespace:
    base = {
        "active_ad_count": 2,
        "continuity_score": 0.8,
        "longest_running_active_days": 180,
        "opportunity_score": 75,
        "distinct_creative_count": 2,
        "active_creative_count": 2,
        "creative_refresh_rate": 0.2,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_ideal_advertiser_qualifies() -> None:
    verdict = qualifies(_advertiser(), IcpProfile())
    assert verdict.qualified is True
    assert verdict.disqualifiers == []


def test_prolific_tester_excluded_by_distinct_ceiling() -> None:
    # 40 distinct creatives, otherwise a strong long-runner: must be excluded.
    adv = _advertiser(
        distinct_creative_count=40, active_creative_count=30, creative_refresh_rate=6.0
    )
    verdict = qualifies(adv, IcpProfile())
    assert verdict.qualified is False
    assert any("already testing at scale" in d for d in verdict.disqualifiers)


def test_high_refresh_excluded() -> None:
    adv = _advertiser(creative_refresh_rate=5.0)
    verdict = qualifies(adv, IcpProfile())
    assert verdict.qualified is False
    assert any("iterating too actively" in d for d in verdict.disqualifiers)


def test_short_runner_excluded() -> None:
    adv = _advertiser(longest_running_active_days=10)
    verdict = qualifies(adv, IcpProfile())
    assert verdict.qualified is False
    assert any("longest-run" in d for d in verdict.disqualifiers)


def test_inconsistent_spender_excluded() -> None:
    adv = _advertiser(continuity_score=0.2)
    verdict = qualifies(adv, IcpProfile())
    assert verdict.qualified is False


def test_no_active_ads_excluded() -> None:
    adv = _advertiser(active_ad_count=0)
    verdict = qualifies(adv, IcpProfile())
    assert verdict.qualified is False


def test_from_overrides_partial() -> None:
    profile = IcpProfile.from_overrides(
        {"max_distinct_creatives": 3, "min_opportunity_score": None}
    )
    assert profile.max_distinct_creatives == 3
    # None values fall back to defaults.
    assert profile.min_opportunity_score == IcpProfile().min_opportunity_score
    # A borderline advertiser with 5 distinct creatives now fails the tighter cap.
    assert qualifies(_advertiser(distinct_creative_count=5), profile).qualified is False
