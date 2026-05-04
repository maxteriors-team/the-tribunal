"""Tests for app.utils.datetime — time string parsing."""

from datetime import time

from app.utils.datetime import parse_time_string


class TestParseTimeString:
    """Tests for parse_time_string."""

    def test_valid_morning(self) -> None:
        """Valid morning time parses correctly."""
        assert parse_time_string("09:30") == time(9, 30)

    def test_valid_end_of_day(self) -> None:
        """23:59 parses correctly."""
        assert parse_time_string("23:59") == time(23, 59)

    def test_valid_midnight(self) -> None:
        """00:00 parses correctly."""
        assert parse_time_string("00:00") == time(0, 0)

    def test_valid_single_digit_hour(self) -> None:
        """Single-digit hour like '9:00' parses."""
        assert parse_time_string("9:00") == time(9, 0)

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        assert parse_time_string(None) is None

    def test_invalid_alpha_returns_none(self) -> None:
        """Non-numeric input returns None."""
        assert parse_time_string("abc") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert parse_time_string("") is None

    def test_hour_out_of_range_returns_none(self) -> None:
        """Hour > 23 returns None."""
        assert parse_time_string("25:00") is None

    def test_minute_out_of_range_returns_none(self) -> None:
        """Minute > 59 returns None."""
        assert parse_time_string("10:99") is None

    def test_no_colon_returns_none(self) -> None:
        """String without colon returns None."""
        assert parse_time_string("0930") is None

    def test_only_hour_returns_none(self) -> None:
        """Only hour part returns None (IndexError)."""
        assert parse_time_string("09") is None

    def test_non_integer_parts_returns_none(self) -> None:
        """Non-integer hour/minute returns None."""
        assert parse_time_string("ab:cd") is None
