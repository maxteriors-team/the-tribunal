"""Season windows and lead-time grading (pure — no database).

The calendar rules a pre-booking campaign lives or dies on: a season that wraps
the new year is one season, February knows how long it is, and September really
is the right month to build a January campaign.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.prebooking.season import (
    AMPLE_LEAD_DAYS,
    TIGHT_LEAD_DAYS,
    assess_lead_time,
    describe_season,
    lead_time_days,
    month_name,
    next_season_year,
    resolve_season_window,
)


class TestResolveSeasonWindow:
    def test_spring_season_resolves_to_first_and_last_day(self) -> None:
        window = resolve_season_window(start_month=3, end_month=5, year=2027)
        assert window.start == date(2027, 3, 1)
        assert window.end == date(2027, 5, 31)
        assert window.days == 92

    def test_season_wrapping_the_new_year_ends_in_the_following_year(self) -> None:
        """Holiday lighting sold as November-January is one season, not two."""
        window = resolve_season_window(start_month=11, end_month=1, year=2026)
        assert window.start == date(2026, 11, 1)
        assert window.end == date(2027, 1, 31)

    def test_single_month_season(self) -> None:
        window = resolve_season_window(start_month=6, end_month=6, year=2027)
        assert window.start == date(2027, 6, 1)
        assert window.end == date(2027, 6, 30)

    def test_february_length_follows_the_calendar(self) -> None:
        assert resolve_season_window(start_month=2, end_month=2, year=2027).end == date(
            2027, 2, 28
        )
        assert resolve_season_window(start_month=2, end_month=2, year=2028).end == date(
            2028, 2, 29
        )

    def test_wrapping_season_into_a_leap_february(self) -> None:
        window = resolve_season_window(start_month=12, end_month=2, year=2027)
        assert window.start == date(2027, 12, 1)
        assert window.end == date(2028, 2, 29)

    @pytest.mark.parametrize("month", [0, 13, -1])
    def test_month_outside_the_calendar_is_refused(self, month: int) -> None:
        with pytest.raises(ValueError, match="between 1 and 12"):
            resolve_season_window(start_month=month, end_month=5, year=2027)


class TestDescribeSeason:
    def test_same_year_range(self) -> None:
        assert describe_season(start_month=3, end_month=5, year=2027) == "March–May 2027"

    def test_single_month(self) -> None:
        assert describe_season(start_month=6, end_month=6, year=2027) == "June 2027"

    def test_wrapping_range_names_both_years(self) -> None:
        assert (
            describe_season(start_month=11, end_month=1, year=2026)
            == "November 2026–January 2027"
        )

    def test_month_name(self) -> None:
        assert month_name(1) == "January"
        assert month_name(12) == "December"


class TestLeadTime:
    def test_september_build_for_a_january_season_is_ample(self) -> None:
        """The rule the whole feature exists to teach."""
        days = lead_time_days(launch_on=date(2026, 9, 1), season_start=date(2027, 1, 1))
        assert days == 122
        assert assess_lead_time(days).status == "ample"

    def test_ample_boundary(self) -> None:
        assert assess_lead_time(AMPLE_LEAD_DAYS).status == "ample"
        assert assess_lead_time(AMPLE_LEAD_DAYS - 1).status == "tight"

    def test_tight_boundary(self) -> None:
        assert assess_lead_time(TIGHT_LEAD_DAYS).status == "tight"
        assert assess_lead_time(TIGHT_LEAD_DAYS - 1).status == "late"

    def test_building_a_spring_campaign_in_march_is_late(self) -> None:
        days = lead_time_days(launch_on=date(2027, 3, 20), season_start=date(2027, 4, 1))
        assert days == 12
        assessment = assess_lead_time(days)
        assert assessment.status == "late"
        assert "fill-the-calendar" in assessment.message

    def test_season_already_started_reports_negative_lead_and_says_so(self) -> None:
        days = lead_time_days(launch_on=date(2027, 5, 1), season_start=date(2027, 3, 1))
        assert days == -61
        assessment = assess_lead_time(days)
        assert assessment.status == "late"
        assert "started" in assessment.message
        assert assessment.weeks == -8

    def test_weeks_rounds_toward_zero(self) -> None:
        assert assess_lead_time(20).weeks == 2
        assert assess_lead_time(122).weeks == 17


class TestNextSeasonYear:
    def test_a_january_season_planned_in_september_means_next_year(self) -> None:
        assert next_season_year(start_month=1, today=date(2026, 9, 15)) == 2027

    def test_a_later_month_this_year_stays_this_year(self) -> None:
        assert next_season_year(start_month=11, today=date(2026, 9, 15)) == 2026

    def test_the_current_month_rolls_forward(self) -> None:
        """Mid-September is too late to pre-sell September; mean next year."""
        assert next_season_year(start_month=9, today=date(2026, 9, 15)) == 2027
