"""Tests for best-effort free-form US address parsing.

Shapes are taken from real public lead-form submissions: Google-formatted
strings when the funnel ran a satellite measurement, hand-typed fragments
when it didn't.
"""

from app.services.contacts.address_parsing import ParsedAddress, parse_us_address


class TestGoogleFormatted:
    def test_full_with_country(self) -> None:
        assert parse_us_address("31555 Kennoway Ct, Beverly Hills, MI 48025, USA") == (
            ParsedAddress("31555 Kennoway Ct", "Beverly Hills", "MI", "48025")
        )

    def test_full_without_country(self) -> None:
        assert parse_us_address("14040 Pernell Dr, Sterling Heights, MI 48313") == (
            ParsedAddress("14040 Pernell Dr", "Sterling Heights", "MI", "48313")
        )

    def test_zip_plus_four(self) -> None:
        parsed = parse_us_address("1 Main St, Troy, MI 48083-1234")
        assert parsed is not None
        assert parsed.zip_code == "48083-1234"

    def test_united_states_suffix(self) -> None:
        parsed = parse_us_address("1 Main St, Troy, MI 48083, United States")
        assert parsed == ParsedAddress("1 Main St", "Troy", "MI", "48083")


class TestHandTyped:
    def test_missing_comma_before_state(self) -> None:
        """Real submission: '12845 Culver Dr, Shelby Township MI 48315'."""
        assert parse_us_address("12845 Culver Dr, Shelby Township MI 48315") == (
            ParsedAddress("12845 Culver Dr", "Shelby Township", "MI", "48315")
        )

    def test_city_state_no_zip(self) -> None:
        assert parse_us_address("44735 Larkspur Ln, Novi, MI") == (
            ParsedAddress("44735 Larkspur Ln", "Novi", "MI", None)
        )

    def test_lowercase_state_is_uppercased(self) -> None:
        parsed = parse_us_address("1 Main St, Troy, mi 48083")
        assert parsed is not None
        assert parsed.state == "MI"

    def test_street_only_falls_back_to_line1(self) -> None:
        assert parse_us_address("32044 Holly Dr.") == ParsedAddress("32044 Holly Dr.")

    def test_unparseable_never_loses_text(self) -> None:
        raw = "the yellow house across from the park"
        assert parse_us_address(raw) == ParsedAddress(raw)

    def test_whitespace_is_collapsed(self) -> None:
        parsed = parse_us_address("  1 Main St,   Troy,  MI   48083  ")
        assert parsed == ParsedAddress("1 Main St", "Troy", "MI", "48083")


class TestEmpty:
    def test_empty_string(self) -> None:
        assert parse_us_address("") is None

    def test_whitespace_only(self) -> None:
        assert parse_us_address("   ,  ") is None
