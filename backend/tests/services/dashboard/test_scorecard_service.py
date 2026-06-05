"""Unit tests for the receptionist scorecard aggregation logic.

These exercise the pure ``aggregate_scorecard`` / helper functions directly with
fabricated rows, so the metric maths is covered without a database.
"""

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.services.dashboard.scorecard_service import (
    AppointmentRow,
    CallRow,
    InboundReplyRow,
    OpportunityRow,
    TextbackRow,
    aggregate_scorecard,
    resolve_range,
)

UTC_TZ = ZoneInfo("UTC")
START = date(2026, 1, 1)
END = date(2026, 1, 31)


def _call(
    *,
    conversation_id: uuid.UUID | None = None,
    contact_id: int | None = 1,
    created_at: datetime | None = None,
    status: str = "completed",
    channel: str = "voice",
    duration_seconds: int | None = 120,
    outcome_type: str | None = "completed",
    signals: dict | None = None,
) -> CallRow:
    return CallRow(
        conversation_id=conversation_id or uuid.uuid4(),
        contact_id=contact_id,
        created_at=created_at or datetime(2026, 1, 10, 15, 0, tzinfo=UTC),
        status=status,
        channel=channel,
        duration_seconds=duration_seconds,
        outcome_type=outcome_type,
        signals=signals or {},
    )


def _aggregate(**overrides):
    kwargs = {
        "start_date": START,
        "end_date": END,
        "calls": [],
        "textbacks": [],
        "inbound_replies": [],
        "appointments": [],
        "opportunities": [],
        "tz": UTC_TZ,
    }
    kwargs.update(overrides)
    return aggregate_scorecard(**kwargs)


class TestAnswering:
    def test_empty_window_has_null_rates(self) -> None:
        card = _aggregate()
        assert card.calls_total == 0
        assert card.calls_answered == 0
        assert card.answer_rate is None
        assert card.recovery_rate is None
        assert card.after_hours_coverage_rate is None
        assert card.avg_handle_time_seconds is None

    def test_answer_rate_and_handle_time(self) -> None:
        calls = [
            _call(outcome_type="completed", duration_seconds=60),
            _call(outcome_type="appointment_booked", duration_seconds=180),
            _call(outcome_type="no_answer", duration_seconds=None),
        ]
        card = _aggregate(calls=calls)
        assert card.calls_total == 3
        assert card.calls_answered == 2
        assert card.answer_rate == round(2 / 3 * 100, 1)
        # Average of answered call durations only (60, 180) -> 120.
        assert card.avg_handle_time_seconds == 120.0

    def test_status_fallback_when_no_outcome(self) -> None:
        calls = [_call(outcome_type=None, status="answered")]
        card = _aggregate(calls=calls)
        assert card.calls_answered == 1

    def test_voicemail_channel_counts_as_missed(self) -> None:
        calls = [_call(channel="voicemail", outcome_type=None, status="initiated")]
        card = _aggregate(calls=calls)
        assert card.missed_calls == 1
        assert card.calls_answered == 0


class TestMissedRecovery:
    def test_missed_call_recovered_by_inbound_reply(self) -> None:
        conv = uuid.uuid4()
        t = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
        calls = [
            _call(
                conversation_id=conv,
                created_at=t,
                outcome_type="no_answer",
                status="no_answer",
            )
        ]
        textbacks = [TextbackRow(conversation_id=conv, created_at=t)]
        replies = [
            InboundReplyRow(
                conversation_id=conv, created_at=datetime(2026, 1, 10, 9, 5, tzinfo=UTC)
            )
        ]
        card = _aggregate(calls=calls, textbacks=textbacks, inbound_replies=replies)
        assert card.missed_calls == 1
        assert card.missed_calls_textback_sent == 1
        assert card.missed_calls_recovered == 1
        assert card.recovery_rate == 100.0

    def test_missed_call_recovered_by_appointment(self) -> None:
        conv = uuid.uuid4()
        t = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
        calls = [
            _call(
                conversation_id=conv,
                contact_id=42,
                created_at=t,
                outcome_type="busy",
                status="busy",
            )
        ]
        appts = [AppointmentRow(contact_id=42, created_at=datetime(2026, 1, 10, 12, 0, tzinfo=UTC))]
        card = _aggregate(calls=calls, appointments=appts)
        assert card.missed_calls_recovered == 1
        assert card.appointments_booked == 1

    def test_missed_call_not_recovered_when_reply_precedes_call(self) -> None:
        conv = uuid.uuid4()
        t = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
        calls = [
            _call(conversation_id=conv, created_at=t, outcome_type="rejected", status="rejected")
        ]
        replies = [
            InboundReplyRow(
                conversation_id=conv, created_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC)
            )
        ]
        card = _aggregate(calls=calls, inbound_replies=replies)
        assert card.missed_calls == 1
        assert card.missed_calls_recovered == 0


class TestAfterHours:
    def test_after_hours_classification(self) -> None:
        # 02:00 UTC weekday -> after hours; 15:00 UTC weekday -> business hours.
        after = _call(created_at=datetime(2026, 1, 8, 2, 0, tzinfo=UTC))  # Thursday
        during = _call(created_at=datetime(2026, 1, 8, 15, 0, tzinfo=UTC))
        card = _aggregate(calls=[after, during], tz=UTC_TZ)
        assert card.after_hours_calls == 1
        assert card.after_hours_answered == 1
        assert card.after_hours_coverage_rate == 100.0

    def test_weekend_is_after_hours(self) -> None:
        weekend = _call(created_at=datetime(2026, 1, 10, 15, 0, tzinfo=UTC))  # Saturday
        card = _aggregate(calls=[weekend], tz=UTC_TZ)
        assert card.after_hours_calls == 1


class TestRevenueAndReasons:
    def test_revenue_and_deposits(self) -> None:
        opps = [
            OpportunityRow(
                amount=1000.0,
                created_at=datetime(2026, 1, 5, tzinfo=UTC),
                status="open",
                closed_date=None,
            ),
            OpportunityRow(
                amount=500.0,
                created_at=datetime(2026, 1, 6, tzinfo=UTC),
                status="won",
                closed_date=date(2026, 1, 7),
            ),
        ]
        card = _aggregate(opportunities=opps)
        assert card.revenue_booked == 1500.0
        assert card.deposits_booked == 500.0
        assert card.currency == "USD"

    def test_top_call_reasons_ranked(self) -> None:
        calls = [
            _call(signals={"intents": ["pricing", "booking"]}),
            _call(signals={"intents": ["pricing"]}),
            _call(signals={"topics": ["hours"]}),
        ]
        card = _aggregate(calls=calls)
        reasons = {r.reason: r.count for r in card.top_call_reasons}
        assert reasons["pricing"] == 2
        assert reasons["booking"] == 1
        assert reasons["hours"] == 1
        # Most common is first.
        assert card.top_call_reasons[0].reason == "pricing"


class TestResolveRange:
    def test_defaults_to_last_30_days(self) -> None:
        today = date(2026, 2, 1)
        start, end = resolve_range(None, None, today=today)
        assert end == today
        assert (end - start).days == 29

    def test_swaps_inverted_range(self) -> None:
        start, end = resolve_range(date(2026, 3, 10), date(2026, 3, 1))
        assert start == date(2026, 3, 1)
        assert end == date(2026, 3, 10)


def test_resolve_range_uses_now_when_no_today() -> None:
    start, end = resolve_range(None, None)
    assert end <= datetime.now(UTC).date()
    assert start <= end
