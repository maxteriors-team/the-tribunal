"""Unit tests for capacity maths: job sizing, backlog weeks, estimate utilization.

These drive the pure helpers with fabricated ``JobFact`` rows, so every guard is
covered without a database (the DB paths — the status pre-filter, the carried
crew capacity and the appointment window — live in ``test_capacity_query.py``,
marked ``integration``).

The rules under test, in the language of the report:

- backlog is work **sold but not delivered**: ``completed`` work already shipped
  and ``cancelled`` work was never sold, so counting either reports fuel that
  does not exist;
- a job's size is its booked window when it has one, and an assumption when it
  does not — refusing to estimate would render the deepest possible queue (all
  unscheduled) as an empty backlog;
- capacity is an owner-entered nullable field, so an unset or non-positive one
  makes ``backlog_weeks`` ``None`` — never ``0``, never a ``ZeroDivisionError``;
- ``at_capacity`` is likewise ``None`` when no ceiling was set: "not full" cannot
  be claimed off a number nobody entered.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.models.field_service import JobStatus
from app.services.reporting.capacity_service import (
    AT_CAPACITY_THRESHOLD_PCT,
    DEFAULT_JOB_HOURS,
    OPEN_JOB_STATUSES,
    JobFact,
    assemble_backlog,
    assemble_estimate_capacity,
    job_hours,
)

AS_OF = date(2026, 7, 15)
JUNE = date(2026, 6, 1)
# A Monday morning start, so windows read like a real dispatch board.
START = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)


def _windowed(hours: float, *, status: JobStatus = JobStatus.SCHEDULED) -> JobFact:
    """A job with a booked window of ``hours``."""
    return JobFact(
        status=status,
        scheduled_start=START,
        scheduled_end=START + timedelta(hours=hours),
    )


def _queued(status: JobStatus = JobStatus.UNSCHEDULED) -> JobFact:
    """A job with no window at all (sold, not yet on the calendar)."""
    return JobFact(status=status)


# --------------------------------------------------------------------------- #
# Per-job sizing
# --------------------------------------------------------------------------- #
def test_job_hours_prefers_the_booked_window() -> None:
    assert job_hours(_windowed(6.5)) == 6.5


def test_job_hours_falls_back_to_the_default_without_a_window() -> None:
    assert job_hours(_queued()) == DEFAULT_JOB_HOURS
    assert job_hours(_queued(), default_hours=7.5) == 7.5


@pytest.mark.parametrize(
    "start, end",
    [
        (START, None),  # half-filled window (start only)
        (None, START),  # half-filled window (end only)
        (START, START),  # zero-length
        (START, START - timedelta(hours=2)),  # reversed (import artifact)
    ],
)
def test_job_hours_falls_back_for_an_unusable_window(
    start: datetime | None, end: datetime | None
) -> None:
    """An unmeasurable window is an assumption, not zero hours of work."""
    fact = JobFact(status=JobStatus.SCHEDULED, scheduled_start=start, scheduled_end=end)
    assert job_hours(fact, default_hours=5.0) == 5.0


def test_job_hours_refuses_a_non_positive_default() -> None:
    """A zero default would silently erase every unscheduled job from the gauge."""
    assert job_hours(_queued(), default_hours=0) == DEFAULT_JOB_HOURS
    assert job_hours(_queued(), default_hours=-3) == DEFAULT_JOB_HOURS


# --------------------------------------------------------------------------- #
# Backlog
# --------------------------------------------------------------------------- #
def test_backlog_is_empty_for_a_workspace_with_no_jobs() -> None:
    report = assemble_backlog([], as_of=AS_OF, weekly_capacity_hours=40.0)

    assert report.job_count == 0
    assert report.unscheduled_job_count == 0
    assert report.backlog_hours == 0.0
    # Capacity is known and the queue really is empty, so zero weeks is the
    # honest answer here — unlike the unknown-capacity case below.
    assert report.backlog_weeks == 0.0
    assert report.as_of == AS_OF


def test_backlog_sums_windows_and_assumptions_into_weeks() -> None:
    # 8h + 6h booked, plus two jobs sized at the 4h default = 22h.
    facts = [
        _windowed(8),
        _windowed(6),
        _queued(),
        _queued(status=JobStatus.IN_PROGRESS),
    ]
    report = assemble_backlog(facts, as_of=AS_OF, weekly_capacity_hours=40.0)

    assert report.backlog_hours == 22.0
    assert report.weekly_capacity_hours == 40.0
    assert report.backlog_weeks == 0.55
    assert report.job_count == 4
    # Only the UNSCHEDULED one is off the calendar; the in-progress job is on it.
    assert report.unscheduled_job_count == 1
    # Both window-less jobs were sized by assumption, whatever their status.
    assert report.assumed_duration_job_count == 2
    assert report.default_job_hours == DEFAULT_JOB_HOURS


def test_backlog_honours_a_custom_default_job_size() -> None:
    report = assemble_backlog(
        [_queued(), _queued()], as_of=AS_OF, weekly_capacity_hours=40.0, default_job_hours=10.0
    )
    assert report.backlog_hours == 20.0
    assert report.backlog_weeks == 0.5
    assert report.default_job_hours == 10.0


def test_backlog_excludes_completed_and_cancelled_work() -> None:
    """Delivered work is not backlog and cancelled work was never sold."""
    facts = [
        _windowed(8),
        _windowed(40, status=JobStatus.COMPLETED),
        _windowed(40, status=JobStatus.CANCELLED),
        _queued(status=JobStatus.COMPLETED),
        _queued(status=JobStatus.CANCELLED),
    ]
    report = assemble_backlog(facts, as_of=AS_OF, weekly_capacity_hours=40.0)

    assert report.job_count == 1
    assert report.backlog_hours == 8.0
    assert report.backlog_weeks == 0.2
    assert report.unscheduled_job_count == 0
    assert report.assumed_duration_job_count == 0


def test_only_open_statuses_count_as_backlog() -> None:
    """Pin the rule itself, so a new JobStatus cannot join the backlog silently."""
    assert set(OPEN_JOB_STATUSES) == {
        JobStatus.UNSCHEDULED,
        JobStatus.SCHEDULED,
        JobStatus.IN_PROGRESS,
    }
    assert JobStatus.COMPLETED not in OPEN_JOB_STATUSES
    assert JobStatus.CANCELLED not in OPEN_JOB_STATUSES


@pytest.mark.parametrize("capacity", [None, 0.0, -40.0])
def test_backlog_weeks_is_none_when_capacity_is_unusable(capacity: float | None) -> None:
    """The whole point of the guard: no crew size means no gauge, not a crash."""
    report = assemble_backlog([_windowed(8)], as_of=AS_OF, weekly_capacity_hours=capacity)

    assert report.backlog_hours == 8.0
    assert report.backlog_weeks is None
    assert report.weekly_capacity_hours is None
    # The hours are still reported: the numerator is knowable even when the
    # divisor is not, and "8 hours booked" beats no answer at all.
    assert report.job_count == 1


def test_backlog_weeks_is_none_for_an_empty_workspace_with_no_capacity() -> None:
    report = assemble_backlog([], as_of=AS_OF, weekly_capacity_hours=None)

    assert report.backlog_hours == 0.0
    assert report.backlog_weeks is None
    assert report.below_alert_threshold is None


def test_backlog_flags_a_thinning_pipeline_against_the_alert_threshold() -> None:
    """40h against a 40h week is 1 week booked — under a 3-week comfort line."""
    report = assemble_backlog(
        [_windowed(40)], as_of=AS_OF, weekly_capacity_hours=40.0, alert_weeks=3.0
    )
    assert report.backlog_weeks == 1.0
    assert report.alert_weeks == 3.0
    assert report.below_alert_threshold is True


def test_backlog_is_not_flagged_when_comfortably_booked_out() -> None:
    report = assemble_backlog(
        [_windowed(200)], as_of=AS_OF, weekly_capacity_hours=40.0, alert_weeks=3.0
    )
    assert report.backlog_weeks == 5.0
    assert report.below_alert_threshold is False


@pytest.mark.parametrize("alert", [None, 0.0, -1.0])
def test_backlog_alert_is_none_without_a_usable_threshold(alert: float | None) -> None:
    report = assemble_backlog(
        [_windowed(40)], as_of=AS_OF, weekly_capacity_hours=40.0, alert_weeks=alert
    )
    assert report.alert_weeks is None
    assert report.below_alert_threshold is None


# --------------------------------------------------------------------------- #
# Estimate capacity
# --------------------------------------------------------------------------- #
def test_estimate_capacity_reports_utilization_as_a_percent() -> None:
    report = assemble_estimate_capacity(period_month=JUNE, booked=45, capacity=60)

    assert report.period_month == JUNE
    assert report.booked == 45
    assert report.capacity == 60
    assert report.utilization_pct == 75.0
    assert report.at_capacity is False
    assert report.at_capacity_threshold_pct == AT_CAPACITY_THRESHOLD_PCT


def test_estimate_capacity_normalizes_any_day_to_its_month() -> None:
    report = assemble_estimate_capacity(period_month=date(2026, 6, 14), booked=0, capacity=60)
    assert report.period_month == JUNE


def test_estimate_capacity_trips_the_hire_trigger_at_the_threshold() -> None:
    """Exactly at the line counts as full: 68/80 is 85.0%."""
    report = assemble_estimate_capacity(period_month=JUNE, booked=68, capacity=80)
    assert report.utilization_pct == AT_CAPACITY_THRESHOLD_PCT
    assert report.at_capacity is True


def test_estimate_capacity_reports_overbooking_past_one_hundred_percent() -> None:
    report = assemble_estimate_capacity(period_month=JUNE, booked=90, capacity=60)
    assert report.utilization_pct == 150.0
    assert report.at_capacity is True


@pytest.mark.parametrize("capacity", [None, 0])
def test_estimate_capacity_is_unknown_without_a_stored_ceiling(capacity: int | None) -> None:
    """No ceiling means no verdict — 'not full' would be a claim, not a fact."""
    report = assemble_estimate_capacity(period_month=JUNE, booked=70, capacity=capacity)

    assert report.booked == 70
    assert report.utilization_pct is None
    assert report.at_capacity is None


def test_estimate_capacity_reports_an_empty_month_as_wide_open() -> None:
    report = assemble_estimate_capacity(period_month=JUNE, booked=0, capacity=60)
    assert report.utilization_pct == 0.0
    assert report.at_capacity is False
