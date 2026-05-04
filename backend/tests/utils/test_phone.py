"""Tests for app.utils.phone — E.164 normalization and validation."""

import pytest

from app.utils.phone import (
    PhoneNumberError,
    normalize_phone_e164,
    normalize_phone_safe,
    validate_phone_number,
)


class TestNormalizePhoneE164:
    """Tests for normalize_phone_e164."""

    def test_valid_us_number_10_digits(self) -> None:
        """10-digit US number normalizes to E.164."""
        result = normalize_phone_e164("4155552671")
        assert result == "+14155552671"

    def test_valid_us_number_with_dashes(self) -> None:
        """US number with dashes normalizes correctly."""
        result = normalize_phone_e164("415-555-2671")
        assert result == "+14155552671"

    def test_valid_us_number_with_parens(self) -> None:
        """US number with parens normalizes correctly."""
        result = normalize_phone_e164("(415) 555-2671")
        assert result == "+14155552671"

    def test_valid_us_number_with_country_code(self) -> None:
        """US number already with country code normalizes correctly."""
        result = normalize_phone_e164("+14155552671")
        assert result == "+14155552671"

    def test_valid_international_uk(self) -> None:
        """Valid UK number with country code normalizes."""
        # UK mobile number in E.164
        result = normalize_phone_e164("+442071838750")
        assert result == "+442071838750"

    def test_valid_international_with_country_override(self) -> None:
        """International number parsed with explicit country."""
        result = normalize_phone_e164("020 7183 8750", country="GB")
        assert result == "+442071838750"

    def test_empty_string_raises(self) -> None:
        """Empty string raises PhoneNumberError."""
        with pytest.raises(PhoneNumberError, match="empty"):
            normalize_phone_e164("")

    def test_whitespace_only_raises(self) -> None:
        """Whitespace-only string raises PhoneNumberError."""
        with pytest.raises(PhoneNumberError, match="empty"):
            normalize_phone_e164("   ")

    def test_invalid_number_raises(self) -> None:
        """Invalid number (wrong length) raises PhoneNumberError."""
        with pytest.raises(PhoneNumberError):
            normalize_phone_e164("1")

    def test_non_parseable_raises(self) -> None:
        """Garbage input raises PhoneNumberError."""
        with pytest.raises(PhoneNumberError):
            normalize_phone_e164("not-a-phone-number-at-all")

    def test_invalid_us_area_code_raises(self) -> None:
        """Invalid US area code raises PhoneNumberError."""
        # Area code 000 is invalid in US
        with pytest.raises(PhoneNumberError):
            normalize_phone_e164("0001234567")

    def test_phone_number_error_is_value_error(self) -> None:
        """PhoneNumberError is a ValueError subclass."""
        assert issubclass(PhoneNumberError, ValueError)


class TestValidatePhoneNumber:
    """Tests for validate_phone_number."""

    def test_valid_returns_true(self) -> None:
        """Valid US number returns True."""
        assert validate_phone_number("+14155552671") is True

    def test_valid_with_formatting_returns_true(self) -> None:
        """Formatted US number returns True."""
        assert validate_phone_number("(415) 555-2671") is True

    def test_invalid_returns_false(self) -> None:
        """Invalid short number returns False."""
        assert validate_phone_number("123") is False

    def test_empty_returns_false(self) -> None:
        """Empty string returns False."""
        assert validate_phone_number("") is False

    def test_garbage_returns_false(self) -> None:
        """Garbage string returns False."""
        assert validate_phone_number("not-a-phone") is False

    def test_uk_with_country_returns_true(self) -> None:
        """Valid UK number with country param returns True."""
        assert validate_phone_number("020 7183 8750", country="GB") is True


class TestNormalizePhoneSafe:
    """Tests for normalize_phone_safe."""

    def test_valid_returns_e164(self) -> None:
        """Valid input returns E.164 formatted string."""
        result = normalize_phone_safe("415-555-2671")
        assert result == "+14155552671"

    def test_invalid_returns_none(self) -> None:
        """Invalid input returns None."""
        result = normalize_phone_safe("123")
        assert result is None

    def test_empty_returns_none(self) -> None:
        """Empty string returns None."""
        assert normalize_phone_safe("") is None

    def test_garbage_returns_none(self) -> None:
        """Unparseable string returns None."""
        assert normalize_phone_safe("xyz") is None

    def test_international_country_override(self) -> None:
        """International number with country override normalizes."""
        result = normalize_phone_safe("020 7183 8750", country="GB")
        assert result == "+442071838750"
