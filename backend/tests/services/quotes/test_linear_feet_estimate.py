"""Unit tests for the roofline permanent-vs-temporary comparison math.

Pure (no DB / no marker, so they run in the default suite). Exercises
``QuoteService._compute_comparison`` directly with hand-built pricing configs so
the estimator's dollar math, multi-year projection, disabled-service handling,
and feet-privacy contract are all locked down without touching Postgres.
"""

from __future__ import annotations

from app.schemas.estimate import LinearFeetEstimateRequest
from app.schemas.pricing import (
    ChristmasConfig,
    FinancingConfig,
    PermanentConfig,
    PricingSettings,
)
from app.services.quotes.quote_service import QuoteService


def _config(**overrides) -> PricingSettings:
    """A pricing config with both holiday services enabled and no gross-up buffer.

    ``fee_buffer=0`` keeps the arithmetic exact so expected dollars are obvious.
    """
    base = {
        # Zero buffer + no cash/commission adjustments -> net == displayed.
        "financing": FinancingConfig(enabled=True, fee_buffer=0.0),
        "permanent": PermanentConfig(
            enabled=True,
            per_ft=30,
            controller_base=300,
            per_channel=0,
            included_channels=1,
            minimum=0,
        ),
        "christmas": ChristmasConfig(
            enabled=True,
            roofline_per_ft=6,
            takedown_enabled=True,
            takedown_rate=0.25,
            storage_price=0,
            minimum=0,
        ),
        "comparison_years": 5,
    }
    base.update(overrides)
    return PricingSettings(**base)


def _estimate(config: PricingSettings, feet: float, **kw):
    req = LinearFeetEstimateRequest(feet=feet, **kw)
    return QuoteService._compute_comparison(config, req)


def test_both_services_priced_from_feet() -> None:
    result = _estimate(_config(), 100)

    # Permanent: 100ft * $30 + $300 controller = $3,300.
    assert result.permanent.enabled is True
    assert result.permanent.total == 3300
    assert result.permanent.per_ft == 30
    # Christmas: 100ft * $6 = $600.
    assert result.christmas.enabled is True
    assert result.christmas.total == 600
    # Single-season difference is absolute.
    assert result.difference == 2700
    assert result.feet == 100


def test_multi_year_savings_projection() -> None:
    result = _estimate(_config(), 100)

    # Temporary recurs every season: $600 * 5 = $3,000. Permanent one-time $3,300.
    assert result.years == 5
    assert result.temporary_multi_year == 3000
    assert result.permanent_one_time == 3300
    # Over 5 seasons permanent costs $300 more (negative "savings" here) — sign is
    # honest so the UI can frame it correctly.
    assert result.multi_year_savings == -300


def test_multi_year_savings_favors_permanent_over_longer_horizon() -> None:
    result = _estimate(_config(comparison_years=10), 100)

    assert result.years == 10
    assert result.temporary_multi_year == 6000
    assert result.multi_year_savings == 2700  # 6000 - 3300


def test_takedown_increases_temporary_cost() -> None:
    with_takedown = _estimate(_config(), 100, takedown=True)
    # 25% of the $600 net install added: $600 + $150 = $750.
    assert with_takedown.christmas.total == 750


def test_permanent_disabled_zeros_that_side_and_skips_savings() -> None:
    config = _config(permanent=PermanentConfig(enabled=False))
    result = _estimate(config, 100)

    assert result.permanent.enabled is False
    assert result.permanent.total == 0
    assert result.christmas.total == 600
    # With only one option offered, comparison figures are not asserted as savings.
    assert result.difference == 0
    assert result.multi_year_savings == 0


def test_christmas_disabled_zeros_that_side() -> None:
    config = _config(christmas=ChristmasConfig(enabled=False))
    result = _estimate(config, 100)

    assert result.christmas.enabled is False
    assert result.christmas.total == 0
    assert result.permanent.total == 3300
    assert result.difference == 0


def test_permanent_minimum_applied() -> None:
    config = _config(
        permanent=PermanentConfig(
            enabled=True, per_ft=30, controller_base=0, minimum=5000
        )
    )
    result = _estimate(config, 100)
    # 100 * 30 = 3000 -> lifted to the $5,000 minimum.
    assert result.permanent.total == 5000


def test_internal_per_ft_override_adjusts_permanent_only() -> None:
    config = _config()
    standard = _estimate(config, 100)
    overridden = _estimate(config, 100, per_ft_override=45)

    # Permanent bills the internal rate: 100ft * $45 + $300 controller = $4,800.
    assert overridden.permanent.per_ft == 45
    assert overridden.permanent.total == 4800
    # Seasonal roofline is untouched by the permanent linear-ft override.
    assert overridden.christmas.total == standard.christmas.total == 600
    # The workspace's customer-facing rate is never mutated by the override.
    assert config.permanent.per_ft == 30
    assert standard.permanent.total == 3300


def test_per_ft_override_none_uses_configured_rate() -> None:
    config = _config()
    assert _estimate(config, 100, per_ft_override=None).permanent.total == 3300


def test_internal_christmas_per_ft_override_adjusts_seasonal_only() -> None:
    config = _config()
    standard = _estimate(config, 100)
    overridden = _estimate(config, 100, christmas_per_ft_override=9)

    # Seasonal bills the internal rate: 100ft * $9 = $900.
    assert overridden.christmas.per_ft == 9
    assert overridden.christmas.total == 900
    # Permanent is untouched by the seasonal override.
    assert overridden.permanent.total == standard.permanent.total == 3300
    # The workspace's customer-facing rate is never mutated.
    assert config.christmas.roofline_per_ft == 6
    assert standard.christmas.total == 600


def test_both_per_ft_overrides_apply_independently() -> None:
    result = _estimate(_config(), 100, per_ft_override=45, christmas_per_ft_override=9)
    assert result.permanent.total == 4800  # 100*45 + 300
    assert result.christmas.total == 900  # 100*9
    assert result.permanent.per_ft == 45
    assert result.christmas.per_ft == 9


def test_perks_default_copy_present() -> None:
    result = _estimate(_config(), 50)
    assert len(result.permanent_perks) >= 3
    assert len(result.christmas_perks) >= 3
    assert all(isinstance(p, str) and p for p in result.permanent_perks)


def test_zero_feet_yields_zero_totals() -> None:
    result = _estimate(_config(), 0)
    # No measured roofline -> no job on either side (permanent short-circuits to
    # $0 rather than billing a bare controller).
    assert result.christmas.total == 0
    assert result.permanent.total == 0
    assert result.difference == 0
    assert result.multi_year_savings == 0
