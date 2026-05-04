"""Tests for app.utils.calendar — Cal.com booking URL generation."""

from urllib.parse import parse_qs, urlparse

from app.utils.calendar import generate_booking_url


class TestGenerateBookingUrl:
    """Tests for generate_booking_url."""

    def test_event_type_id_only(self) -> None:
        """Event type ID alone produces base URL with no query string."""
        url = generate_booking_url(event_type_id=123456)
        assert url == "https://cal.com/event/123456"

    def test_all_contact_params(self) -> None:
        """All contact params produce full URL-encoded query string."""
        url = generate_booking_url(
            event_type_id=123456,
            contact_email="john@example.com",
            contact_name="John Doe",
            contact_phone="+15551234567",
        )
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "cal.com"
        assert parsed.path == "/event/123456"
        qs = parse_qs(parsed.query)
        assert qs["email"] == ["john@example.com"]
        assert qs["name"] == ["John Doe"]
        assert qs["phone"] == ["+15551234567"]

    def test_workspace_slug_produces_workspace_url(self) -> None:
        """Custom workspace_slug uses workspace path."""
        url = generate_booking_url(
            event_type_id=999,
            workspace_slug="acme",
        )
        assert url == "https://cal.com/acme/999"

    def test_workspace_slug_cal_treated_as_default(self) -> None:
        """workspace_slug='cal' is treated as default and uses /event/ path."""
        url = generate_booking_url(
            event_type_id=42,
            workspace_slug="cal",
        )
        assert url == "https://cal.com/event/42"

    def test_workspace_slug_none_uses_event_path(self) -> None:
        """workspace_slug=None uses /event/ path."""
        url = generate_booking_url(event_type_id=42, workspace_slug=None)
        assert url == "https://cal.com/event/42"

    def test_workspace_slug_empty_uses_event_path(self) -> None:
        """workspace_slug='' is falsy and uses /event/ path."""
        url = generate_booking_url(event_type_id=42, workspace_slug="")
        assert url == "https://cal.com/event/42"

    def test_workspace_slug_with_contact_params(self) -> None:
        """Workspace slug combined with contact params."""
        url = generate_booking_url(
            event_type_id=10,
            contact_email="x@y.com",
            workspace_slug="myteam",
        )
        assert url.startswith("https://cal.com/myteam/10?")
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert qs["email"] == ["x@y.com"]

    def test_url_encoding_special_chars_in_name(self) -> None:
        """Special characters in name are URL-encoded."""
        url = generate_booking_url(
            event_type_id=1,
            contact_name="John & Jane",
        )
        # & must be escaped in query string
        assert "John+%26+Jane" in url or "John%20%26%20Jane" in url
        # Round-trip decoding should work
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert qs["name"] == ["John & Jane"]

    def test_url_encoding_email_at_symbol(self) -> None:
        """@ in email is URL-encoded."""
        url = generate_booking_url(
            event_type_id=1,
            contact_email="a@b.com",
        )
        # @ becomes %40 in query
        assert "%40" in url
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert qs["email"] == ["a@b.com"]

    def test_url_encoding_phone_plus(self) -> None:
        """+ in phone number is URL-encoded."""
        url = generate_booking_url(
            event_type_id=1,
            contact_phone="+15551234567",
        )
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert qs["phone"] == ["+15551234567"]

    def test_only_email_param(self) -> None:
        """Only email produces URL with only email query."""
        url = generate_booking_url(event_type_id=5, contact_email="x@y.com")
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert qs == {"email": ["x@y.com"]}

    def test_name_and_phone_only(self) -> None:
        """Only name and phone produce URL without email."""
        url = generate_booking_url(
            event_type_id=5,
            contact_name="Jane",
            contact_phone="+15551234567",
        )
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert "email" not in qs
        assert qs["name"] == ["Jane"]
        assert qs["phone"] == ["+15551234567"]

    def test_empty_string_contact_params_excluded(self) -> None:
        """Empty strings are falsy and excluded from query."""
        url = generate_booking_url(
            event_type_id=5,
            contact_email="",
            contact_name="",
            contact_phone="",
        )
        assert url == "https://cal.com/event/5"
