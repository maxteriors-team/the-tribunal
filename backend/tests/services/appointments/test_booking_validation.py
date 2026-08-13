"""Booking requests are validated before the agent can confirm them.

Each case here is a confirmation the customer would otherwise have believed: a
slot in the past, an invite mailed into a void, a "30 minute" job blocked out for
a week.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.appointments.booking_validation import (
    MAX_DURATION_MINUTES,
    is_on_site_service,
    is_valid_email,
    validate_booking_request,
)

NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 6, 10, 9, 0, tzinfo=NEW_YORK)


def _validate(**overrides):
    kwargs = {
        "date_str": "2026-06-11",
        "time_str": "14:00",
        "email": "dana@example.com",
        "duration_minutes": 60,
        "tz": NEW_YORK,
        "now": NOW,
    }
    kwargs.update(overrides)
    return validate_booking_request(**kwargs)


class TestEmail:
    @pytest.mark.parametrize(
        "email",
        ["dana@example.com", "d.reyes+jobs@mail.example.co.uk"],
    )
    def test_accepts_deliverable_shapes(self, email: str) -> None:
        assert is_valid_email(email)
        assert _validate(email=email).valid

    @pytest.mark.parametrize(
        "email",
        [None, "", "dana", "dana@localhost", "dana example@mail.com", "@example.com"],
    )
    def test_rejects_undeliverable_shapes(self, email) -> None:
        assert not is_valid_email(email)
        result = _validate(email=email)
        assert not result.valid
        assert result.error == "invalid_email"


class TestDatetime:
    def test_accepts_a_future_slot(self) -> None:
        result = _validate()
        assert result.valid
        assert result.scheduled_at == datetime(2026, 6, 11, 14, 0, tzinfo=NEW_YORK)

    def test_rejects_the_past(self) -> None:
        result = _validate(date_str="2026-06-09")
        assert not result.valid
        assert result.error == "datetime_in_past"

    def test_rejects_now_itself(self) -> None:
        result = _validate(date_str="2026-06-10", time_str="09:00")
        assert not result.valid
        assert result.error == "datetime_in_past"

    @pytest.mark.parametrize(
        ("date_str", "time_str"),
        [("06/11/2026", "14:00"), ("2026-06-11", "2pm"), ("2026-13-40", "14:00"), ("", "")],
    )
    def test_rejects_unparseable_input(self, date_str: str, time_str: str) -> None:
        result = _validate(date_str=date_str, time_str=time_str)
        assert not result.valid
        assert result.error == "invalid_datetime"

    def test_wall_clock_is_interpreted_in_the_booking_zone(self) -> None:
        """2 PM Eastern must not be stamped as 2 PM UTC — that ships a 4h error."""
        result = _validate()
        assert result.scheduled_at is not None
        assert result.scheduled_at.utcoffset().total_seconds() == -4 * 3600


class TestDuration:
    @pytest.mark.parametrize("duration", [0, -30, 1, MAX_DURATION_MINUTES + 1, 10_000])
    def test_rejects_out_of_range(self, duration: int) -> None:
        result = _validate(duration_minutes=duration)
        assert not result.valid
        assert result.error == "invalid_duration"

    @pytest.mark.parametrize("duration", ["sixty", None, [30]])
    def test_rejects_non_numeric(self, duration) -> None:
        result = _validate(duration_minutes=duration)
        assert not result.valid
        assert result.error == "invalid_duration"

    def test_accepts_numeric_strings_from_the_model(self) -> None:
        assert _validate(duration_minutes="45").valid


class TestServiceType:
    def test_optional_by_default(self) -> None:
        assert _validate(service_type=None).valid

    def test_required_when_asked(self) -> None:
        result = _validate(service_type="  ", require_service_type=True)
        assert not result.valid
        assert result.error == "missing_service_type"

    @pytest.mark.parametrize(
        "service_type",
        ["Exterior Cleaning", "On-site estimate", "Gutter install"],
    )
    def test_on_site_work_needs_an_address(self, service_type: str) -> None:
        assert is_on_site_service(service_type)
        result = _validate(service_type=service_type, contact_address="")
        assert not result.valid
        assert result.error == "missing_address"

        assert _validate(service_type=service_type, contact_address="123 Main St, Austin TX").valid

    def test_remote_work_does_not_need_an_address(self) -> None:
        assert not is_on_site_service("Phone consult")
        assert _validate(service_type="Phone consult", contact_address=None).valid


def test_failures_render_as_a_model_readable_tool_result() -> None:
    result = _validate(email="nope")
    payload = result.as_tool_result()
    assert payload["success"] is False
    assert payload["error"] == "invalid_email"
    assert payload["message"]
    assert payload["alternative_slots"] == []
