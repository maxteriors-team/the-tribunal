"""Unit tests for the receptionist scorecard aggregation logic.

These exercise the pure ``aggregate_scorecard`` / helper functions directly with
fabricated rows, so the metric maths is covered without a database.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from app.models.attendance import ATTENDANCE_STATUS_COMPLETE
from app.models.field_service import Technician
from app.models.workspace import Workspace
from app.services.dashboard.scorecard_service import (
    AppointmentRow,
    CallRow,
    InboundReplyRow,
    LeadRow,
    ScorecardService,
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
        "revenue_booked": 0.0,
        "deposits_collected": 0.0,
        "leads": [],
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
    def test_revenue_and_deposits_use_canonical_ledger_totals(self) -> None:
        card = _aggregate(revenue_booked=1500.0, deposits_collected=500.0)
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


class TestNewLeadsByDay:
    def test_series_covers_every_day_in_range_zero_filled(self) -> None:
        # Two leads on Jan 2, none on any other day.
        leads = [
            LeadRow(created_at=datetime(2026, 1, 2, 9, 0, tzinfo=UTC)),
            LeadRow(created_at=datetime(2026, 1, 2, 21, 30, tzinfo=UTC)),
        ]
        card = _aggregate(leads=leads)

        # One entry per day of the inclusive Jan 1 – Jan 31 range.
        assert len(card.new_leads_by_day) == 31
        assert card.new_leads_by_day[0].date == date(2026, 1, 1)
        assert card.new_leads_by_day[-1].date == date(2026, 1, 31)
        # Ascending, contiguous — no gaps.
        dates = [d.date for d in card.new_leads_by_day]
        assert dates == sorted(dates)

        by_date = {d.date: d.count for d in card.new_leads_by_day}
        assert by_date[date(2026, 1, 2)] == 2
        # A quiet day is an explicit zero, not a missing entry.
        assert by_date[date(2026, 1, 3)] == 0
        assert card.new_leads_total == 2

    def test_empty_range_totals_zero_but_keeps_series(self) -> None:
        card = _aggregate()
        assert card.new_leads_total == 0
        assert len(card.new_leads_by_day) == 31
        assert all(d.count == 0 for d in card.new_leads_by_day)
        assert card.avg_new_leads_per_day == 0.0

    def test_average_is_per_day_of_range(self) -> None:
        leads = [LeadRow(created_at=datetime(2026, 1, 5, 12, 0, tzinfo=UTC)) for _ in range(62)]
        card = _aggregate(leads=leads)
        # 62 leads over 31 days.
        assert card.avg_new_leads_per_day == 2.0

    def test_buckets_by_workspace_local_day_not_utc(self) -> None:
        # 01:30 UTC on Jan 6 is still the evening of Jan 5 in New York. An owner
        # who took that lead "yesterday evening" must not see it on today's bar.
        leads = [LeadRow(created_at=datetime(2026, 1, 6, 1, 30, tzinfo=UTC))]
        card = _aggregate(leads=leads, tz=ZoneInfo("America/New_York"))

        by_date = {d.date: d.count for d in card.new_leads_by_day}
        assert by_date[date(2026, 1, 5)] == 1
        assert by_date[date(2026, 1, 6)] == 0

    def test_naive_timestamps_are_treated_as_utc(self) -> None:
        leads = [LeadRow(created_at=datetime(2026, 1, 9, 15, 0))]
        card = _aggregate(leads=leads)
        by_date = {d.date: d.count for d in card.new_leads_by_day}
        assert by_date[date(2026, 1, 9)] == 1

    def test_leads_outside_range_are_excluded(self) -> None:
        leads = [
            LeadRow(created_at=datetime(2025, 12, 31, 12, 0, tzinfo=UTC)),
            LeadRow(created_at=datetime(2026, 2, 1, 12, 0, tzinfo=UTC)),
            LeadRow(created_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC)),
        ]
        card = _aggregate(leads=leads)
        assert card.new_leads_total == 1

    def test_single_day_range(self) -> None:
        leads = [LeadRow(created_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC))]
        card = _aggregate(leads=leads, start_date=date(2026, 1, 1), end_date=date(2026, 1, 1))
        assert len(card.new_leads_by_day) == 1
        assert card.new_leads_by_day[0].count == 1
        assert card.avg_new_leads_per_day == 1.0


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


def _mock_result(
    *,
    scalars: list[object] | None = None,
    rows: list[tuple[object, ...]] | None = None,
) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = scalars or []
    result.all.return_value = rows or []
    return result


async def test_technician_activity_returns_scoped_unranked_context() -> None:
    workspace_id = uuid.uuid4()
    workspace = Workspace(
        id=workspace_id,
        name="Test workspace",
        slug="test-workspace",
        settings={"timezone": "UTC"},
    )
    alex = Technician(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        user_id=101,
        name="Alex Tech",
        is_active=True,
    )
    blair = Technician(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name="Blair Tech",
        is_active=False,
    )
    job_one = uuid.uuid4()
    job_two = uuid.uuid4()
    crew_job = uuid.uuid4()
    entry_start = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)

    db = AsyncMock()
    db.execute.side_effect = [
        _mock_result(scalars=[alex, blair]),
        _mock_result(rows=[(alex.id, job_one), (alex.id, job_two)]),
        # job_one is also crew-routed and must still count only once.
        _mock_result(rows=[(alex.id, job_one), (blair.id, crew_job)]),
        _mock_result(
            rows=[
                (alex.id, entry_start, entry_start + timedelta(hours=1)),
                (alex.id, entry_start, entry_start + timedelta(minutes=30)),
                # A malformed negative interval is completed context but adds no time.
                (blair.id, entry_start, entry_start - timedelta(minutes=5)),
            ]
        ),
        _mock_result(
            rows=[
                (101, entry_start, entry_start + timedelta(hours=8), 3_600),
                (101, entry_start, entry_start - timedelta(minutes=1), 120),
            ]
        ),
    ]

    rows = await ScorecardService(db).get_technician_activity(
        workspace,
        date(2026, 1, 1),
        date(2026, 1, 31),
    )

    assert [row.name for row in rows] == ["Alex Tech", "Blair Tech"]
    assert rows[0].model_dump() == {
        "id": alex.id,
        "name": "Alex Tech",
        "active": True,
        "assigned_jobs": 2,
        "completed_job_time_entries": 2,
        "job_logged_seconds": 5_400,
        "attendance_worked_seconds": 25_200,
        "attendance_paused_seconds": 3_600,
    }
    assert rows[1].model_dump() == {
        "id": blair.id,
        "name": "Blair Tech",
        "active": False,
        "assigned_jobs": 1,
        "completed_job_time_entries": 1,
        "job_logged_seconds": 0,
        "attendance_worked_seconds": 0,
        "attendance_paused_seconds": 0,
    }

    # Every source query carries the workspace boundary; no cross-workspace rows
    # can enter through unscoped assignments, time entries, or attendance.
    statements = [call.args[0] for call in db.execute.await_args_list]
    assert len(statements) == 5
    for statement in statements:
        assert workspace_id in statement.compile().params.values()

    attendance_statement = statements[-1]
    attendance_params = attendance_statement.compile().params.values()
    assert ATTENDANCE_STATUS_COMPLETE in attendance_params
    attendance_sql = str(attendance_statement)
    assert "attendance_entries.ended_at IS NOT NULL" in attendance_sql


async def test_technician_activity_keeps_empty_roster_to_one_query() -> None:
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Empty workspace",
        slug="empty-workspace",
        settings={"timezone": "UTC"},
    )
    db = AsyncMock()
    db.execute.return_value = _mock_result(scalars=[])

    rows = await ScorecardService(db).get_technician_activity(
        workspace,
        date(2026, 1, 1),
        date(2026, 1, 31),
    )

    assert rows == []
    db.execute.assert_awaited_once()
