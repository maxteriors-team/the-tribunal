"""Unit tests for revenue-target maths: month keys, the backsolve, and pace.

These drive the pure helpers with fabricated dataclasses, so every guard is
covered without a database (the DB paths — upsert, the unique constraint, and
the actuals queries — live in ``test_revenue_target_query.py``, marked
``integration``).

The rules under test, in the language of the report:

- ``period_month`` names a *month*: any day inside it must key to the same row,
  or one June's goal quietly becomes two;
- the backsolve chain is ``goal -> jobs -> estimates -> leads``, and a missing
  **or** non-positive assumption truncates the chain at that link rather than
  dividing by zero or reporting a confident ``0``;
- an explicit ``target_leads`` is the owner's own number and beats the derived
  one;
- linear pace counts today as elapsed, so the 1st projects from 1/30th of a
  month and the last day projects exactly what was sold;
- a month with no target still reports its actuals — the dashboard needs to
  prompt "set a goal", not render an error.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.revenue_target import (
    CK_PERIOD_MONTH_FIRST_DAY,
    DEFAULT_ASSUMED_SAT_RATE,
    UQ_WORKSPACE_MONTH,
    RevenueTarget,
)
from app.schemas.revenue_target import RevenueTargetBulkUpsert, RevenueTargetUpsert
from app.services.reporting.revenue_target_service import (
    MonthActuals,
    TargetAssumptions,
    assemble_pace,
    backsolve_funnel,
    days_elapsed_in_month,
    month_bounds,
    normalize_month,
)

# June 2026: 30 days, and the month a pressure-washing shop actually earns in.
JUNE = date(2026, 6, 1)

# A goal that backsolves to round numbers: $130,000 at a $1,300 ticket is 100
# jobs; at a 40% close rate that is 250 estimates; at a 50% sat rate, 500 leads.
FULL_TARGET = TargetAssumptions(
    revenue_goal=130_000.0,
    target_avg_job_value=1_300.0,
    target_close_rate=40.0,
    assumed_sat_rate=50.0,
)


def _stages(pace) -> dict[str, object]:
    return {stage.stage: stage for stage in pace.stages}


# --------------------------------------------------------------------------- #
# Month normalization
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("day", [1, 2, 14, 30])
def test_any_day_in_a_month_normalizes_to_the_first(day: int) -> None:
    assert normalize_month(date(2026, 6, day)) == JUNE


def test_normalizing_an_already_normal_month_is_a_no_op() -> None:
    assert normalize_month(JUNE) == JUNE


@pytest.mark.parametrize(
    ("value", "expected_last"),
    [
        (date(2026, 6, 14), date(2026, 6, 30)),
        (date(2026, 7, 31), date(2026, 7, 31)),
        (date(2026, 2, 10), date(2026, 2, 28)),
        # Leap February: the month length must come from the calendar, never a
        # hardcoded 30/31, or the last day of Feb 2028 projects one day short.
        (date(2028, 2, 10), date(2028, 2, 29)),
    ],
)
def test_month_bounds_span_the_whole_calendar_month(value: date, expected_last: date) -> None:
    first, last = month_bounds(value)

    assert first == value.replace(day=1)
    assert last == expected_last


def test_one_target_per_workspace_per_month_is_declared() -> None:
    """The upsert keys on this constraint, so its shape is part of the contract."""
    unique = [c for c in RevenueTarget.__table__.constraints if isinstance(c, UniqueConstraint)]

    assert len(unique) == 1
    assert unique[0].name == UQ_WORKSPACE_MONTH
    assert [column.name for column in unique[0].columns] == ["workspace_id", "period_month"]


def test_period_month_is_pinned_to_the_first_by_a_check_constraint() -> None:
    """Normalizing in the service is not enough — scripts write rows too."""
    checks = {
        c.name
        for c in RevenueTarget.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name
    }

    # ``app.db.base.NAMING_CONVENTION`` prefixes bare check names with the table.
    assert f"ck_revenue_targets_{CK_PERIOD_MONTH_FIRST_DAY}" in checks


def test_bulk_upsert_refuses_the_same_month_twice() -> None:
    """Two entries for June would key to one row and one would silently win."""
    with pytest.raises(ValidationError, match="Duplicate target months"):
        RevenueTargetBulkUpsert(
            targets=[
                RevenueTargetUpsert(period_month=date(2026, 6, 1), revenue_goal=130_000),
                # Same month, different day — normalization makes these collide.
                RevenueTargetUpsert(period_month=date(2026, 6, 14), revenue_goal=45_000),
            ]
        )


def test_bulk_upsert_accepts_a_season_of_distinct_months() -> None:
    payload = RevenueTargetBulkUpsert(
        targets=[
            RevenueTargetUpsert(period_month=date(2026, 1, 1), revenue_goal=45_000),
            RevenueTargetUpsert(period_month=date(2026, 6, 1), revenue_goal=130_000),
        ]
    )

    assert [target.revenue_goal for target in payload.targets] == [45_000, 130_000]
    # The sat rate is an assumption with an industry default, not a required input.
    assert payload.targets[0].assumed_sat_rate == DEFAULT_ASSUMED_SAT_RATE


# --------------------------------------------------------------------------- #
# Elapsed days
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("today", "expected"),
    [
        # Today counts as elapsed: a month is 1/30th done on the 1st, not 0/30ths.
        (date(2026, 6, 1), (1, 30)),
        (date(2026, 6, 15), (15, 30)),
        (date(2026, 6, 30), (30, 30)),
        # A finished month is fully elapsed, however long ago it ended.
        (date(2026, 9, 9), (30, 30)),
        # A month that has not started cannot be extrapolated from.
        (date(2026, 5, 31), (0, 30)),
    ],
)
def test_days_elapsed_counts_today_and_clamps_outside_the_month(
    today: date, expected: tuple[int, int]
) -> None:
    assert days_elapsed_in_month(JUNE, today) == expected


# --------------------------------------------------------------------------- #
# Backsolve
# --------------------------------------------------------------------------- #
def test_backsolve_walks_the_goal_down_the_funnel() -> None:
    required = backsolve_funnel(FULL_TARGET)

    assert required.jobs == pytest.approx(100.0)
    assert required.estimates == pytest.approx(250.0)
    assert required.leads == pytest.approx(500.0)


def test_backsolve_uses_the_default_sat_rate_when_the_owner_never_touched_it() -> None:
    required = backsolve_funnel(
        TargetAssumptions(
            revenue_goal=130_000.0,
            target_avg_job_value=1_300.0,
            target_close_rate=40.0,
            assumed_sat_rate=DEFAULT_ASSUMED_SAT_RATE,
        )
    )

    assert required.leads == pytest.approx(250 / 0.6)


def test_an_explicit_lead_target_beats_the_derived_one() -> None:
    """A number the owner typed is a decision; the backsolve is only an estimate."""
    required = backsolve_funnel(
        TargetAssumptions(
            revenue_goal=130_000.0,
            target_avg_job_value=1_300.0,
            target_close_rate=40.0,
            assumed_sat_rate=50.0,
            target_leads=600,
        )
    )

    assert required.leads == pytest.approx(600.0)
    # Only the lead stage is overridden; the rest of the chain is untouched.
    assert required.estimates == pytest.approx(250.0)


def test_no_goal_means_every_stage_is_unknown() -> None:
    required = backsolve_funnel(TargetAssumptions())

    assert (required.jobs, required.estimates, required.leads) == (None, None, None)


def test_a_missing_average_job_value_truncates_the_whole_chain() -> None:
    """Without a ticket size there is no job count, so nothing downstream exists."""
    required = backsolve_funnel(
        TargetAssumptions(revenue_goal=130_000.0, target_close_rate=40.0, assumed_sat_rate=50.0)
    )

    assert (required.jobs, required.estimates, required.leads) == (None, None, None)


@pytest.mark.parametrize("avg_job_value", [0.0, -1_300.0])
def test_a_non_positive_job_value_is_unknown_not_a_division_error(avg_job_value: float) -> None:
    """The schema rejects these, but a script or a legacy row can still deliver one."""
    required = backsolve_funnel(
        TargetAssumptions(
            revenue_goal=130_000.0,
            target_avg_job_value=avg_job_value,
            target_close_rate=40.0,
            assumed_sat_rate=50.0,
        )
    )

    assert required.jobs is None


@pytest.mark.parametrize("close_rate", [None, 0.0, -40.0])
def test_a_missing_or_zero_close_rate_stops_at_jobs(close_rate: float | None) -> None:
    required = backsolve_funnel(
        TargetAssumptions(
            revenue_goal=130_000.0,
            target_avg_job_value=1_300.0,
            target_close_rate=close_rate,
            assumed_sat_rate=50.0,
        )
    )

    # Jobs only need the ticket size, so they survive.
    assert required.jobs == pytest.approx(100.0)
    assert required.estimates is None
    assert required.leads is None


@pytest.mark.parametrize("sat_rate", [None, 0.0, -50.0])
def test_a_missing_or_zero_sat_rate_stops_at_estimates(sat_rate: float | None) -> None:
    required = backsolve_funnel(
        TargetAssumptions(
            revenue_goal=130_000.0,
            target_avg_job_value=1_300.0,
            target_close_rate=40.0,
            assumed_sat_rate=sat_rate,
        )
    )

    assert required.estimates == pytest.approx(250.0)
    assert required.leads is None


def test_a_zero_goal_backsolves_to_zero_not_to_unknown() -> None:
    """A seasonal shutdown month is a real goal of 0, not a missing goal."""
    required = backsolve_funnel(
        TargetAssumptions(
            revenue_goal=0.0,
            target_avg_job_value=1_300.0,
            target_close_rate=40.0,
            assumed_sat_rate=50.0,
        )
    )

    assert (required.jobs, required.estimates, required.leads) == (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
# Pace
# --------------------------------------------------------------------------- #
def test_pace_on_day_one_projects_from_a_single_day() -> None:
    pace = assemble_pace(
        FULL_TARGET,
        MonthActuals(revenue_sold_to_date=10_000.0, leads=20, estimates=8, sold=3),
        period_month=JUNE,
        today=date(2026, 6, 1),
        has_target=True,
    )

    assert (pace.days_elapsed, pace.days_in_month) == (1, 30)
    assert pace.revenue_sold_to_date == 10_000.0
    # "At this rate" on the 1st really is 30x the day — noisy, but honest, and
    # ``days_elapsed`` tells the client how little to trust it yet.
    assert pace.projected_month_end == 300_000.0
    assert pace.gap_to_goal == 120_000.0
    assert pace.projected_gap_to_goal == -170_000.0
    assert pace.on_pace is True

    stages = _stages(pace)
    assert stages["sold"].actual == 3
    assert stages["sold"].required == 100.0
    # One day into a 30-day month, only 1/30th of the requirement is due.
    assert stages["sold"].required_to_date == pytest.approx(3.33)
    assert stages["estimates"].required_to_date == pytest.approx(8.33)


def test_pace_on_the_last_day_projects_exactly_what_sold() -> None:
    pace = assemble_pace(
        FULL_TARGET,
        MonthActuals(revenue_sold_to_date=100_000.0, leads=410, estimates=205, sold=77),
        period_month=JUNE,
        today=date(2026, 6, 30),
        has_target=True,
    )

    assert (pace.days_elapsed, pace.days_in_month) == (30, 30)
    # A finished month has nothing left to extrapolate: projection == actual.
    assert pace.projected_month_end == 100_000.0
    assert pace.gap_to_goal == 30_000.0
    assert pace.projected_gap_to_goal == 30_000.0
    assert pace.on_pace is False

    stages = _stages(pace)
    # The whole month is due, so required_to_date has caught up with required.
    assert stages["leads"].required_to_date == stages["leads"].required == 500.0
    assert stages["leads"].gap == pytest.approx(90.0)
    assert stages["sold"].gap == pytest.approx(23.0)


def test_a_month_that_has_not_started_projects_nothing() -> None:
    """Zero elapsed days is the division guard on the projection itself."""
    pace = assemble_pace(
        FULL_TARGET,
        MonthActuals(),
        period_month=JUNE,
        today=date(2026, 5, 20),
        has_target=True,
    )

    assert pace.days_elapsed == 0
    assert pace.projected_month_end is None
    assert pace.projected_gap_to_goal is None
    assert pace.on_pace is None
    # The goal is still known, so what is left to sell is still answerable.
    assert pace.gap_to_goal == 130_000.0


def test_a_month_with_no_target_still_reports_its_actuals() -> None:
    pace = assemble_pace(
        TargetAssumptions(),
        MonthActuals(revenue_sold_to_date=42_000.0, leads=90, estimates=30, sold=12),
        period_month=JUNE,
        today=date(2026, 6, 15),
        has_target=False,
    )

    assert pace.has_target is False
    assert pace.revenue_goal is None
    assert pace.gap_to_goal is None
    assert pace.on_pace is None
    # Trailing revenue never depended on a goal, so it is still reported.
    assert pace.revenue_sold_to_date == 42_000.0
    assert pace.projected_month_end == pytest.approx(84_000.0)

    stages = _stages(pace)
    assert stages["leads"].actual == 90
    assert stages["leads"].required is None
    assert stages["leads"].gap is None


def test_pace_flags_a_goal_the_workspace_cannot_physically_deliver() -> None:
    """250 estimates needed against a stated ceiling of 180 is a staffing problem."""
    pace = assemble_pace(
        TargetAssumptions(
            revenue_goal=130_000.0,
            target_avg_job_value=1_300.0,
            target_close_rate=40.0,
            assumed_sat_rate=50.0,
            estimate_capacity_per_month=180,
        ),
        MonthActuals(),
        period_month=JUNE,
        today=date(2026, 6, 10),
        has_target=True,
    )

    assert pace.estimate_capacity_per_month == 180
    assert pace.estimates_over_capacity == pytest.approx(70.0)


def test_capacity_is_silent_when_either_side_is_unknown() -> None:
    pace = assemble_pace(
        TargetAssumptions(revenue_goal=130_000.0, estimate_capacity_per_month=180),
        MonthActuals(),
        period_month=JUNE,
        today=date(2026, 6, 10),
        has_target=True,
    )

    # Required estimates are unknown without a ticket size and close rate, so
    # the comparison reports nothing rather than "180 spare".
    assert pace.estimates_over_capacity is None


def test_pace_normalizes_a_mid_month_period_before_reporting() -> None:
    pace = assemble_pace(
        FULL_TARGET,
        MonthActuals(revenue_sold_to_date=65_000.0),
        period_month=date(2026, 6, 14),
        today=date(2026, 6, 15),
        has_target=True,
    )

    assert pace.period_month == JUNE
    assert pace.days_in_month == 30
