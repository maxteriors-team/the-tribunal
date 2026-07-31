"""Which season a holiday-lighting signup belongs to.

Pure arithmetic, no DB. The cases that matter are the ones a naive
``created_at.year`` gets wrong: a sale made months before the install, a late add
in December, and an add-on in early January while the lights are still on the
house. All three belong to the same season, and a renewal campaign that splits
them either misses last year's customers or texts this year's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.schemas.pricing import ChristmasConfig
from app.services.seasonal import current_season, prior_season_christmas_condition

# A workspace on the shipped defaults: install Nov 15, takedown Jan 8.
DEFAULTS = ChristmasConfig()
# A Detroit operator who starts earlier and pulls lights later.
EARLY = ChristmasConfig(
    season_install_month=10,
    season_install_day=25,
    season_takedown_month=2,
    season_takedown_day=15,
)


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Which season is being sold right now
# --------------------------------------------------------------------------- #
def test_midsummer_is_selling_this_years_season():
    season = current_season(DEFAULTS, now=_at(2026, 7, 30))

    assert season.year == 2026
    assert season.started_at == datetime(2026, 1, 8, tzinfo=UTC)


def test_december_is_still_selling_the_season_it_installed():
    """A late add in December belongs to the season already on the house."""
    assert current_season(DEFAULTS, now=_at(2026, 12, 20)).year == 2026


def test_early_january_before_takedown_is_last_years_season():
    """The lights are still up, so the season has not turned over yet."""
    season = current_season(DEFAULTS, now=_at(2027, 1, 3))

    assert season.year == 2026
    assert season.started_at == datetime(2026, 1, 8, tzinfo=UTC)


def test_the_takedown_anchor_itself_starts_the_new_season():
    assert current_season(DEFAULTS, now=_at(2027, 1, 8)).year == 2027


def test_season_boundary_follows_the_workspaces_own_anchor():
    """A workspace pulling lights in February has a later boundary than default."""
    assert current_season(EARLY, now=_at(2027, 1, 20)).year == 2026
    assert current_season(EARLY, now=_at(2027, 2, 15)).year == 2027


def test_a_february_29_anchor_clamps_on_a_non_leap_year():
    """The config clamps day-per-month, and the season anchor must not explode."""
    config = ChristmasConfig(season_takedown_month=2, season_takedown_day=31)

    season = current_season(config, now=_at(2027, 6, 1))

    assert season.started_at == datetime(2027, 2, 28, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# The predicate itself (shape only; behaviour is proven against a real DB in
# tests/services/prebooking/test_prebooking_flow.py)
# --------------------------------------------------------------------------- #
def test_bounding_seasons_back_adds_a_floor_and_omitting_it_does_not():
    workspace_id = uuid.uuid4()
    season = current_season(DEFAULTS, now=_at(2026, 7, 30))

    unbounded = str(prior_season_christmas_condition(workspace_id, season))
    bounded = str(prior_season_christmas_condition(workspace_id, season, seasons_back=2))

    # Unbounded reaches every earlier season: one ceiling, no floor.
    assert "recurring_job_templates.created_at <" in unbounded
    assert "recurring_job_templates.created_at >=" not in unbounded
    # A bound adds the floor, so the oldest seasons drop out.
    assert "recurring_job_templates.created_at >=" in bounded
