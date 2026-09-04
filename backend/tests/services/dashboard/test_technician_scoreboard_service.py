"""Pure Lighting League rule coverage."""

from decimal import Decimal

import pytest

from app.services.technician_scoreboard import LEVELS, level_for_xp, level_progress, upsell_xp


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (Decimal("0"), 100),
        (Decimal("19.99"), 100),
        (Decimal("20"), 101),
        (Decimal("1999.99"), 199),
        (Decimal("2000"), 200),
        (Decimal("999999"), 200),
    ],
)
def test_approved_upsell_xp_is_floored_and_capped(total: Decimal, expected: int) -> None:
    assert upsell_xp(total) == expected


def test_every_level_threshold_and_lower_boundary() -> None:
    assert len(LEVELS) == 10
    for index, level in enumerate(LEVELS):
        assert level.number == index + 1
        assert level_for_xp(level.lifetime_xp) == level
        if index:
            assert level_for_xp(level.lifetime_xp - 1) == LEVELS[index - 1]


def test_lighting_lord_keeps_accumulating_without_fake_next_level() -> None:
    progress = level_progress(20_000)

    assert progress.level == LEVELS[-1]
    assert progress.next_level is None
    assert progress.xp_into_level == 4_000
    assert progress.xp_to_next_level is None
    assert progress.progress == 1.0
