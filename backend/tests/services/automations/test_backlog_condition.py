"""Unit tests for the ``backlog_below_threshold`` condition decision.

``evaluate_backlog_condition`` is the whole safety story of a trigger pointed at
an entire customer database, so it is tested as a pure function:

* fires when weeks of booked work fall **strictly** below the threshold;
* does not fire at or above it (a backlog exactly on the line is still healthy);
* respects the cooldown — a still-thin backlog stays quiet until it expires, and
  fires again once it does;
* skips when ``backlog_weeks`` is ``None`` (crew capacity unset): an unreadable
  gauge is never read as an empty tank, no matter how long ago it last fired;
* defaults a missing/garbage ``cooldown_days`` to a real cooldown rather than to
  zero, because "no cooldown" is the one failure mode that spams the database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.services.automations.conditions import (
    AUTOMATION_CONDITION_TRIGGERS,
    CONDITION_BACKLOG_BELOW_THRESHOLD,
    DEFAULT_BACKLOG_COOLDOWN_DAYS,
    DEFAULT_BACKLOG_THRESHOLD_WEEKS,
    REASON_BACKLOG_HEALTHY,
    REASON_CAPACITY_UNKNOWN,
    REASON_COOLING_DOWN,
    REASON_FIRE,
    backlog_cooldown_days,
    backlog_threshold_weeks,
    evaluate_backlog_condition,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
CONFIG: dict[str, Any] = {"threshold_weeks": 4.0, "cooldown_days": 14}


def _decide(
    *,
    backlog_weeks: float | None,
    last_triggered_at: datetime | None = None,
    config: dict[str, Any] | None = None,
    now: datetime = NOW,
):
    return evaluate_backlog_condition(
        CONFIG if config is None else config,
        backlog_weeks=backlog_weeks,
        last_triggered_at=last_triggered_at,
        now=now,
    )


def test_trigger_is_registered_as_a_condition() -> None:
    assert CONDITION_BACKLOG_BELOW_THRESHOLD == "backlog_below_threshold"
    assert CONDITION_BACKLOG_BELOW_THRESHOLD in AUTOMATION_CONDITION_TRIGGERS


# --------------------------------------------------------------------------- #
# Threshold                                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("weeks", [0.0, 0.5, 2.0, 3.99])
def test_fires_below_threshold(weeks: float) -> None:
    decision = _decide(backlog_weeks=weeks)

    assert decision.should_fire is True
    assert decision.reason == REASON_FIRE
    assert decision.threshold_weeks == 4.0
    assert decision.cooldown_days == 14


@pytest.mark.parametrize("weeks", [4.0, 4.01, 9.0])
def test_does_not_fire_at_or_above_threshold(weeks: float) -> None:
    """A backlog exactly on the line is healthy — matches ``weeks < threshold``
    in ``BacklogReport.below_alert_threshold``."""
    decision = _decide(backlog_weeks=weeks)

    assert decision.should_fire is False
    assert decision.reason == REASON_BACKLOG_HEALTHY


def test_threshold_comes_from_trigger_config() -> None:
    """6 weeks is thin for a workspace that asked to be warned under 8."""
    decision = _decide(backlog_weeks=6.0, config={"threshold_weeks": 8, "cooldown_days": 7})

    assert decision.should_fire is True
    assert decision.threshold_weeks == 8.0


# --------------------------------------------------------------------------- #
# Cooldown                                                                     #
# --------------------------------------------------------------------------- #


def test_does_not_refire_inside_the_cooldown_window() -> None:
    """The backlog is still thin, but the audience was already contacted."""
    decision = _decide(backlog_weeks=1.0, last_triggered_at=NOW - timedelta(days=13, hours=23))

    assert decision.should_fire is False
    assert decision.reason == REASON_COOLING_DOWN
    assert decision.cooldown_until == NOW + timedelta(hours=1)


def test_fires_again_once_the_cooldown_expires() -> None:
    decision = _decide(backlog_weeks=1.0, last_triggered_at=NOW - timedelta(days=14))

    assert decision.should_fire is True
    assert decision.reason == REASON_FIRE


def test_cooldown_is_measured_from_the_last_fire_not_the_first() -> None:
    """An old fire does not keep the automation muted forever."""
    decision = _decide(backlog_weeks=1.0, last_triggered_at=NOW - timedelta(days=400))

    assert decision.should_fire is True


def test_naive_last_triggered_at_is_treated_as_utc() -> None:
    """A timestamp read back without tzinfo must not raise mid-poll."""
    decision = _decide(
        backlog_weeks=1.0,
        last_triggered_at=(NOW - timedelta(days=1)).replace(tzinfo=None),
    )

    assert decision.should_fire is False
    assert decision.reason == REASON_COOLING_DOWN


@pytest.mark.parametrize("cooldown", [None, 0, -5, "", "abc", True])
def test_missing_or_hostile_cooldown_falls_back_to_a_real_cooldown(cooldown: Any) -> None:
    """Never zero: an uncapped re-fire would text the database every cycle."""
    config = {"threshold_weeks": 4.0, "cooldown_days": cooldown}

    assert backlog_cooldown_days(config) == DEFAULT_BACKLOG_COOLDOWN_DAYS

    decision = _decide(
        backlog_weeks=1.0,
        last_triggered_at=NOW - timedelta(days=1),
        config=config,
    )
    assert decision.should_fire is False
    assert decision.reason == REASON_COOLING_DOWN


def test_fractional_cooldown_still_silences_for_a_whole_day() -> None:
    assert backlog_cooldown_days({"cooldown_days": 0.25}) == 1


def test_string_config_values_are_coerced() -> None:
    """JSONB written by hand or by an older client can hold strings."""
    assert backlog_threshold_weeks({"threshold_weeks": "6.5"}) == 6.5
    assert backlog_cooldown_days({"cooldown_days": "21"}) == 21


@pytest.mark.parametrize("threshold", [None, 0, -1, "nope"])
def test_missing_or_hostile_threshold_falls_back_to_the_home_service_default(
    threshold: Any,
) -> None:
    """A zero threshold can never be met, silently disabling the automation."""
    assert backlog_threshold_weeks({"threshold_weeks": threshold}) == (
        DEFAULT_BACKLOG_THRESHOLD_WEEKS
    )


def test_empty_config_uses_both_defaults() -> None:
    decision = _decide(backlog_weeks=3.0, config={})

    assert decision.should_fire is True
    assert decision.threshold_weeks == DEFAULT_BACKLOG_THRESHOLD_WEEKS
    assert decision.cooldown_days == DEFAULT_BACKLOG_COOLDOWN_DAYS


# --------------------------------------------------------------------------- #
# Unknown capacity                                                             #
# --------------------------------------------------------------------------- #


def test_skips_when_backlog_weeks_is_unknown() -> None:
    """Capacity unset — the gauge is unreadable, not empty."""
    decision = _decide(backlog_weeks=None)

    assert decision.should_fire is False
    assert decision.reason == REASON_CAPACITY_UNKNOWN
    assert decision.backlog_weeks is None


def test_unknown_capacity_outranks_an_expired_cooldown() -> None:
    """A workspace that never set capacity must not fire on its first-ever poll."""
    decision = _decide(backlog_weeks=None, last_triggered_at=NOW - timedelta(days=365))

    assert decision.should_fire is False
    assert decision.reason == REASON_CAPACITY_UNKNOWN


def test_zero_backlog_is_not_unknown() -> None:
    """A genuinely empty calendar (capacity known) is the loudest fire signal."""
    decision = _decide(backlog_weeks=0.0)

    assert decision.should_fire is True
