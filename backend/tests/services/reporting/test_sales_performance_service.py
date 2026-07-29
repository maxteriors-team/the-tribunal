"""Unit tests for sales-performance reporting maths.

These drive the pure :func:`assemble_sales_performance` assembler with
fabricated :class:`QuoteFact` rows, so every rate, median, guard and grouping
rule is covered without a database (the DB join lives in
``test_sales_performance_query.py``, marked ``integration``).

The rules under test, in the language of the report:

- an empty workspace reports ``None``, never a ``ZeroDivisionError`` or a
  misleading ``0``;
- ``draft`` never counts (never reached a customer) and ``sent`` is undecided,
  so neither may move the close rate;
- attach rate counts approved quotes with ``attach_count > 0``, while
  ``avg_attach_value`` averages only over quotes that actually attached;
- a mixed-currency book is refused with the same 422 the other reports raise.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.models.lead_source import LeadSourceType
from app.services.reporting.sales_performance_service import (
    UNASSIGNED_CLOSER_LABEL,
    UNATTRIBUTED_SOURCE_LABEL,
    UNCATEGORIZED_SERVICE_LABEL,
    QuoteFact,
    assemble_sales_performance,
    current_month_window,
    resolve_window,
)

WINDOW_FROM = date(2026, 7, 1)
WINDOW_TO = date(2026, 7, 31)


def _fact(
    status: str,
    total: float = 0.0,
    *,
    attach_count: int = 0,
    attach_value: float = 0.0,
    currency: str | None = "USD",
    primary_service: str | None = None,
    closer_id: int | None = None,
    closer_name: str | None = None,
    lead_source_type: LeadSourceType | None = None,
) -> QuoteFact:
    return QuoteFact(
        status=status,
        total=total,
        attach_count=attach_count,
        attach_value=attach_value,
        currency=currency,
        primary_service=primary_service,
        closer_id=closer_id,
        closer_name=closer_name,
        lead_source_type=lead_source_type,
    )


def _report(*facts: QuoteFact):
    return assemble_sales_performance(facts, date_from=WINDOW_FROM, date_to=WINDOW_TO)


# --------------------------------------------------------------------------- #
# Empty workspace
# --------------------------------------------------------------------------- #
def test_zero_quote_workspace_reports_nulls_not_division_errors() -> None:
    report = _report()

    assert report.quotes_issued == 0
    assert report.quotes_approved == 0
    assert report.revenue_approved == 0.0
    # Every rate/average is undefined, not zero — "no data" must not read as
    # "we close 0% of our quotes".
    assert report.avg_job_value is None
    assert report.median_job_value is None
    assert report.attach_rate is None
    assert report.avg_attach_value is None
    assert report.close_rate is None
    assert report.by_closer == []
    assert report.by_lead_source == []
    assert report.by_primary_service == []
    # Defaults to USD rather than blank when there is nothing to infer from.
    assert report.currency == "USD"
    assert (report.date_from, report.date_to) == (WINDOW_FROM, WINDOW_TO)


def test_a_workspace_with_only_drafts_reports_nothing_issued() -> None:
    report = _report(_fact("draft", 5_000), _fact("draft", 9_000))

    assert report.quotes_issued == 0
    assert report.close_rate is None
    assert report.avg_job_value is None
    assert report.by_closer == []


# --------------------------------------------------------------------------- #
# Job value
# --------------------------------------------------------------------------- #
def test_job_value_averages_and_medians_only_approved_quotes() -> None:
    report = _report(
        _fact("approved", 1_000),
        _fact("approved", 2_000),
        _fact("approved", 9_000),
        # Neither of these is money in the door, so neither may skew job value.
        _fact("declined", 100_000),
        _fact("sent", 100_000),
    )

    assert report.quotes_issued == 5
    assert report.quotes_approved == 3
    assert report.revenue_approved == 12_000.0
    assert report.avg_job_value == 4_000.0
    # The median resists the 9k outlier that drags the mean up.
    assert report.median_job_value == 2_000.0


def test_median_of_an_even_number_of_approvals_averages_the_middle_pair() -> None:
    report = _report(
        _fact("approved", 1_000),
        _fact("approved", 2_000),
        _fact("approved", 3_000),
        _fact("approved", 10_000),
    )

    assert report.median_job_value == 2_500.0
    assert report.avg_job_value == 4_000.0


# --------------------------------------------------------------------------- #
# Close rate
# --------------------------------------------------------------------------- #
def test_close_rate_ignores_draft_and_sent() -> None:
    report = _report(
        _fact("approved", 1_000),
        _fact("declined", 1_000),
        # Undecided (still with the customer) and never-issued: both invisible
        # to the close rate. Counting them would punish quoting recently.
        _fact("sent", 1_000),
        _fact("sent", 1_000),
        _fact("draft", 1_000),
    )

    # 1 approved / (1 approved + 1 declined) — not 1/5 and not 1/4.
    assert report.close_rate == 0.5
    # ...while issued volume still counts the sent quotes (but never the draft).
    assert report.quotes_issued == 4


def test_close_rate_counts_expired_as_a_loss() -> None:
    report = _report(
        _fact("approved", 1_000),
        _fact("declined", 1_000),
        _fact("expired", 1_000),
        _fact("expired", 1_000),
    )

    assert report.close_rate == 0.25


def test_close_rate_is_null_when_nothing_has_been_decided() -> None:
    report = _report(_fact("sent", 1_000), _fact("sent", 2_000), _fact("draft", 3_000))

    assert report.quotes_issued == 2
    assert report.close_rate is None


def test_close_rate_is_one_when_every_decided_quote_closed() -> None:
    report = _report(_fact("approved", 500), _fact("approved", 700), _fact("sent", 900))

    assert report.close_rate == 1.0


# --------------------------------------------------------------------------- #
# Attach metrics
# --------------------------------------------------------------------------- #
def test_attach_rate_is_share_of_approved_quotes_with_an_attachment() -> None:
    report = _report(
        _fact("approved", 1_000, attach_count=1, attach_value=200),
        _fact("approved", 1_000, attach_count=2, attach_value=600),
        _fact("approved", 1_000),
        _fact("approved", 1_000),
        # Unapproved quotes never enter attach maths, however many attachments
        # they carried — nothing was actually sold.
        _fact("declined", 1_000, attach_count=3, attach_value=5_000),
        _fact("draft", 1_000, attach_count=3, attach_value=5_000),
    )

    # 2 of the 4 approved quotes attached something.
    assert report.attach_rate == 0.5
    # ...and the average is over those 2 only: (200 + 600) / 2, not / 4.
    assert report.avg_attach_value == 400.0


def test_attach_rate_counts_a_multi_attachment_quote_once() -> None:
    report = _report(
        _fact("approved", 1_000, attach_count=4, attach_value=800),
        _fact("approved", 1_000),
    )

    assert report.attach_rate == 0.5
    assert report.avg_attach_value == 800.0


def test_attach_rate_is_zero_but_not_null_when_nothing_attached() -> None:
    report = _report(_fact("approved", 1_000), _fact("approved", 2_000))

    # Zero is a real measurement here (we sold, we just never attached), so it
    # must not collapse to null...
    assert report.attach_rate == 0.0
    # ...while the average attach value stays undefined: averaging over an empty
    # set would report a $0 attachment nobody ever sold.
    assert report.avg_attach_value is None


def test_attach_rate_rounds_to_four_decimals() -> None:
    report = _report(
        _fact("approved", 1_000, attach_count=1, attach_value=100),
        _fact("approved", 1_000),
        _fact("approved", 1_000),
    )

    assert report.attach_rate == 0.3333


# --------------------------------------------------------------------------- #
# Currency guard
# --------------------------------------------------------------------------- #
def test_currency_mismatch_raises_the_same_error_as_other_reports() -> None:
    with pytest.raises(HTTPException) as exc:
        _report(_fact("approved", 1_000, currency="USD"), _fact("sent", 2_000, currency="EUR"))

    # Same shape as ARAgingReport / JobPnLSummary: 422 naming both currencies.
    assert exc.value.status_code == 422
    assert "USD" in exc.value.detail
    assert "EUR" in exc.value.detail
    assert "Sales performance" in exc.value.detail


def test_a_single_non_usd_currency_is_reported_as_is() -> None:
    report = _report(_fact("approved", 1_000, currency="GBP"))

    assert report.currency == "GBP"
    assert report.revenue_approved == 1_000.0


def test_a_draft_in_another_currency_does_not_poison_the_report() -> None:
    # The draft is not in the report, so its currency must not trip the guard.
    report = _report(_fact("approved", 1_000, currency="USD"), _fact("draft", 5, currency="EUR"))

    assert report.currency == "USD"


# --------------------------------------------------------------------------- #
# Breakdowns
# --------------------------------------------------------------------------- #
def test_breakdown_by_closer_groups_and_ranks_by_approved_revenue() -> None:
    report = _report(
        _fact("approved", 9_000, closer_id=1, closer_name="Ada Closer"),
        _fact("declined", 1_000, closer_id=1, closer_name="Ada Closer"),
        _fact("approved", 2_000, closer_id=2, closer_name="Bo Rep"),
        _fact("approved", 500),
    )

    labels = [row.label for row in report.by_closer]
    assert labels == ["Ada Closer", "Bo Rep", UNASSIGNED_CLOSER_LABEL]

    ada = report.by_closer[0]
    assert ada.key == "1"
    assert ada.quotes_issued == 2
    assert ada.quotes_approved == 1
    assert ada.revenue_approved == 9_000.0
    assert ada.close_rate == 0.5

    unassigned = report.by_closer[2]
    assert unassigned.key is None
    assert unassigned.revenue_approved == 500.0


def test_breakdown_by_closer_falls_back_to_the_id_when_the_user_has_no_name() -> None:
    report = _report(_fact("approved", 100, closer_id=7))

    assert report.by_closer[0].label == "User #7"
    assert report.by_closer[0].key == "7"


def test_breakdown_by_lead_source_uses_the_shared_channel_labels() -> None:
    report = _report(
        _fact("approved", 8_000, lead_source_type=LeadSourceType.GOOGLE_ADS),
        _fact("approved", 3_000, lead_source_type=LeadSourceType.PHONE_RADIO),
        _fact("declined", 1_000, lead_source_type=LeadSourceType.PHONE_RADIO),
        _fact("approved", 100),
    )

    rows = {row.label: row for row in report.by_lead_source}
    assert set(rows) == {"Google Ads", "Phone / Radio", UNATTRIBUTED_SOURCE_LABEL}
    assert rows["Google Ads"].key == "google_ads"
    assert rows["Google Ads"].revenue_approved == 8_000.0
    assert rows["Phone / Radio"].close_rate == 0.5
    assert rows[UNATTRIBUTED_SOURCE_LABEL].key is None


def test_breakdown_by_primary_service_reports_attach_rate_per_service() -> None:
    report = _report(
        _fact("approved", 4_000, primary_service="roof", attach_count=1, attach_value=400),
        _fact("approved", 6_000, primary_service="roof"),
        _fact("approved", 1_000, primary_service="gutters"),
        _fact("sent", 2_000),
    )

    rows = {row.label: row for row in report.by_primary_service}
    assert set(rows) == {"roof", "gutters", UNCATEGORIZED_SERVICE_LABEL}
    assert rows["roof"].key == "roof"
    assert rows["roof"].quotes_approved == 2
    assert rows["roof"].avg_job_value == 5_000.0
    assert rows["roof"].attach_rate == 0.5
    # An issued-but-undecided quote is a row with volume and no rates.
    assert rows[UNCATEGORIZED_SERVICE_LABEL].quotes_issued == 1
    assert rows[UNCATEGORIZED_SERVICE_LABEL].close_rate is None
    assert rows[UNCATEGORIZED_SERVICE_LABEL].attach_rate is None


def test_breakdown_rows_sum_back_to_the_report_totals() -> None:
    facts = [
        _fact("approved", 1_500, closer_id=1, primary_service="roof"),
        _fact("approved", 2_500, closer_id=2, primary_service="gutters"),
        _fact("declined", 3_000, closer_id=2),
        _fact("sent", 4_000),
        _fact("draft", 9_999),
    ]
    report = _report(*facts)

    for breakdown in (report.by_closer, report.by_lead_source, report.by_primary_service):
        assert sum(row.quotes_issued for row in breakdown) == report.quotes_issued
        assert sum(row.quotes_approved for row in breakdown) == report.quotes_approved
        assert round(sum(row.revenue_approved for row in breakdown), 2) == report.revenue_approved


# --------------------------------------------------------------------------- #
# Window resolution
# --------------------------------------------------------------------------- #
def test_current_month_window_covers_the_whole_calendar_month() -> None:
    assert current_month_window(date(2026, 7, 15)) == (date(2026, 7, 1), date(2026, 7, 31))
    # February in a leap year and a 30-day month both land on the real last day.
    assert current_month_window(date(2028, 2, 10)) == (date(2028, 2, 1), date(2028, 2, 29))
    assert current_month_window(date(2026, 4, 30)) == (date(2026, 4, 1), date(2026, 4, 30))
    assert current_month_window(date(2026, 12, 31)) == (date(2026, 12, 1), date(2026, 12, 31))


def test_missing_window_edges_default_to_the_current_month() -> None:
    today = date(2026, 7, 15)

    assert resolve_window(None, None, today=today) == (date(2026, 7, 1), date(2026, 7, 31))
    assert resolve_window(date(2026, 6, 1), None, today=today) == (
        date(2026, 6, 1),
        date(2026, 7, 31),
    )
    assert resolve_window(None, date(2026, 7, 10), today=today) == (
        date(2026, 7, 1),
        date(2026, 7, 10),
    )


def test_inverted_window_is_refused_rather_than_reported_as_empty() -> None:
    with pytest.raises(HTTPException) as exc:
        resolve_window(date(2026, 7, 31), date(2026, 7, 1))

    assert exc.value.status_code == 422
