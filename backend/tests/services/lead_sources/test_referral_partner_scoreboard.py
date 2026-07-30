"""Tests for the referral-partner scoreboard math and the gone-quiet call list.

These exercise the pure assembly layer with fabricated aggregates (no database),
mirroring ``test_lead_source_roi.py``'s treatment of ``assemble_roi_stats``. The
cases that matter are the ones an operator would notice being wrong: a partner
with no referrals, the denominator each rate divides by, and the exact day a
partner crosses into "gone quiet".
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.models.referral_partner import ReferralPartnerType
from app.services.lead_sources.referral_partner_service import (
    PartnerReferralAggregate,
    build_scoreboard,
    build_scoreboard_row,
    days_since,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
QUIET_AFTER_DAYS = 30


def _aggregate(**overrides: object) -> PartnerReferralAggregate:
    """A partner aggregate with sane defaults, overridable per case."""
    base: dict[str, object] = {
        "partner_id": uuid.uuid4(),
        "name": "Dana Ruiz",
        "company": "Keller Williams",
        "partner_type": ReferralPartnerType.REALTOR,
    }
    base.update(overrides)
    return PartnerReferralAggregate(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Zero referrals
# --------------------------------------------------------------------------- #
def test_partner_with_zero_referrals_reports_unknown_rates_not_zero() -> None:
    """A partner who has never referred has *unknown* rates, not 0%.

    Rendering 0.0 would tell the owner this partner fails to convert, when the
    truth is nobody has asked them for a referral yet.
    """
    row = build_scoreboard_row(_aggregate(), now=NOW, quiet_after_days=QUIET_AFTER_DAYS)

    assert row.referrals_sent == 0
    assert row.jobs_closed == 0
    assert row.close_rate is None
    assert row.average_job_value is None
    assert row.total_revenue == 0.0
    assert row.last_referral_at is None
    assert row.days_since_last_referral is None
    # No history means nothing to have gone quiet *from* — a never-active partner
    # is an activation task, not a win-back call, and must stay off the call list.
    assert row.is_gone_quiet is False


def test_zero_referrals_never_divides_by_zero_even_with_won_jobs() -> None:
    """Revenue with no referral rows still avoids a zero denominator.

    Possible after a partner's referred contacts are deleted while their won jobs
    survive (contact FK is ``SET NULL``). Revenue must remain visible.
    """
    row = build_scoreboard_row(
        _aggregate(referrals_sent=0, referrals_closed=3, jobs_closed=2, total_revenue=4000.0),
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
    )

    assert row.close_rate is None
    assert row.jobs_closed == 2
    assert row.total_revenue == 4000.0
    assert row.average_job_value == 2000.0


def test_empty_scoreboard_totals_are_zero() -> None:
    board = build_scoreboard([], now=NOW, quiet_after_days=QUIET_AFTER_DAYS)

    assert board.items == []
    assert board.total == 0
    assert board.total_referrals_sent == 0
    assert board.total_jobs_closed == 0
    assert board.total_revenue == 0.0


# --------------------------------------------------------------------------- #
# Close-rate and average-job-value denominators
# --------------------------------------------------------------------------- #
def test_close_rate_divides_by_referrals_sent() -> None:
    row = build_scoreboard_row(
        _aggregate(
            referrals_sent=8,
            referrals_closed=2,
            jobs_closed=2,
            total_revenue=5000.0,
        ),
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
    )

    assert row.close_rate == 0.25
    # Average job value divides by *jobs*, not by referrals: two jobs at 2500.
    assert row.average_job_value == 2500.0


def test_repeat_buyer_cannot_push_close_rate_above_one() -> None:
    """One referred lead that bought three times is still a 100% close rate.

    ``jobs_closed`` counts jobs (revenue must be whole), while the rate counts
    the referred leads that converted — so the rate stays a rate.
    """
    row = build_scoreboard_row(
        _aggregate(
            referrals_sent=1,
            referrals_closed=1,
            jobs_closed=3,
            total_revenue=9000.0,
        ),
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
    )

    assert row.close_rate == 1.0
    assert row.jobs_closed == 3
    assert row.average_job_value == 3000.0


def test_converted_count_is_clamped_to_referrals_sent() -> None:
    """A converted count above the referral count is clamped, never >100%."""
    row = build_scoreboard_row(
        _aggregate(referrals_sent=2, referrals_closed=5, jobs_closed=5),
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
    )

    assert row.close_rate == 1.0


def test_referrals_with_no_closed_jobs_report_zero_close_rate() -> None:
    """Real referrals that never closed *are* a 0% close rate — that is signal."""
    row = build_scoreboard_row(
        _aggregate(referrals_sent=6, referrals_closed=0, jobs_closed=0),
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
    )

    assert row.close_rate == 0.0
    assert row.average_job_value is None


def test_won_jobs_with_no_recorded_amount_leave_revenue_at_zero() -> None:
    """A won job with a null amount counts as a job but adds no revenue."""
    row = build_scoreboard_row(
        _aggregate(referrals_sent=1, referrals_closed=1, jobs_closed=1, total_revenue=0.0),
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
    )

    assert row.jobs_closed == 1
    assert row.total_revenue == 0.0
    assert row.average_job_value == 0.0


# --------------------------------------------------------------------------- #
# Gone-quiet boundaries
# --------------------------------------------------------------------------- #
def test_days_since_floors_to_whole_days() -> None:
    assert days_since(NOW - timedelta(days=29, hours=23), NOW) == 29
    assert days_since(NOW - timedelta(days=30), NOW) == 30
    assert days_since(NOW, NOW) == 0
    assert days_since(None, NOW) is None


def test_future_dated_referral_reads_as_today_not_negative() -> None:
    """Clock skew or a backdated import must not produce negative day counts."""
    assert days_since(NOW + timedelta(days=5), NOW) == 0


def test_naive_timestamp_is_treated_as_utc() -> None:
    """Rows read back without a tzinfo must not explode the subtraction."""
    assert days_since(datetime(2026, 7, 20, 12, 0), NOW) == 10


def test_gone_quiet_boundary_is_inclusive_at_the_window() -> None:
    """Exactly N days of silence is quiet; one day short is still active."""
    just_inside = build_scoreboard_row(
        _aggregate(
            referrals_sent=4,
            referrals_closed=2,
            last_referral_at=NOW - timedelta(days=QUIET_AFTER_DAYS - 1),
        ),
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
    )
    exactly_at = build_scoreboard_row(
        _aggregate(
            referrals_sent=4,
            referrals_closed=2,
            last_referral_at=NOW - timedelta(days=QUIET_AFTER_DAYS),
        ),
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
    )

    assert just_inside.days_since_last_referral == QUIET_AFTER_DAYS - 1
    assert just_inside.is_gone_quiet is False
    assert exactly_at.days_since_last_referral == QUIET_AFTER_DAYS
    assert exactly_at.is_gone_quiet is True


def test_gone_quiet_filter_returns_only_partners_with_history() -> None:
    """The call list is win-backs only: history required, silence required."""
    quiet_producer = _aggregate(
        name="Quiet Producer",
        referrals_sent=5,
        referrals_closed=3,
        jobs_closed=3,
        total_revenue=12_000.0,
        last_referral_at=NOW - timedelta(days=QUIET_AFTER_DAYS + 10),
    )
    active_producer = _aggregate(
        name="Active Producer",
        referrals_sent=4,
        referrals_closed=2,
        jobs_closed=2,
        total_revenue=30_000.0,
        last_referral_at=NOW - timedelta(days=2),
    )
    never_referred = _aggregate(name="Never Referred")
    quiet_but_never_closed = _aggregate(
        name="Quiet Dud",
        referrals_sent=2,
        referrals_closed=0,
        last_referral_at=NOW - timedelta(days=QUIET_AFTER_DAYS * 2),
    )

    board = build_scoreboard(
        [quiet_producer, active_producer, never_referred, quiet_but_never_closed],
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
        gone_quiet_only=True,
    )

    names = [row.name for row in board.items]
    assert names == ["Quiet Producer", "Quiet Dud"]
    assert board.gone_quiet_only is True
    assert board.total == 2
    # Totals describe the filtered rows, so the call list never reports the whole
    # network's revenue as if it were at risk.
    assert board.total_revenue == 12_000.0
    assert board.total_referrals_sent == 7


def test_a_wider_window_shrinks_the_call_list() -> None:
    """The window is the operator's knob: 90 days forgives a 45-day gap."""
    partner = _aggregate(
        referrals_sent=3, referrals_closed=1, last_referral_at=NOW - timedelta(days=45)
    )

    assert (
        build_scoreboard([partner], now=NOW, quiet_after_days=30, gone_quiet_only=True).total == 1
    )
    assert (
        build_scoreboard([partner], now=NOW, quiet_after_days=90, gone_quiet_only=True).total == 0
    )


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
def test_scoreboard_sorts_by_revenue_descending() -> None:
    board = build_scoreboard(
        [
            _aggregate(name="Middle", referrals_sent=2, jobs_closed=1, total_revenue=5_000.0),
            _aggregate(name="Top", referrals_sent=1, jobs_closed=1, total_revenue=40_000.0),
            _aggregate(name="Zero"),
            _aggregate(name="Low", referrals_sent=9, jobs_closed=1, total_revenue=900.0),
        ],
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
    )

    assert [row.name for row in board.items] == ["Top", "Middle", "Low", "Zero"]
    assert board.total_revenue == 45_900.0
    assert board.total_jobs_closed == 3
    assert board.total_referrals_sent == 12


def test_equal_revenue_breaks_ties_on_volume_then_name() -> None:
    """Deterministic order, so the table does not reshuffle between refreshes."""
    board = build_scoreboard(
        [
            _aggregate(name="beta", referrals_sent=1, total_revenue=1_000.0, jobs_closed=1),
            _aggregate(name="alpha", referrals_sent=1, total_revenue=1_000.0, jobs_closed=1),
            _aggregate(name="busy", referrals_sent=7, total_revenue=1_000.0, jobs_closed=1),
        ],
        now=NOW,
        quiet_after_days=QUIET_AFTER_DAYS,
    )

    assert [row.name for row in board.items] == ["busy", "alpha", "beta"]
