"""Phone number utilities for E.164 normalization and validation."""

import phonenumbers
import structlog

logger = structlog.get_logger()

DEFAULT_COUNTRY = "US"


class PhoneNumberError(ValueError):
    """Raised when phone number validation/normalization fails."""


def normalize_phone_e164(phone_input: str, country: str = DEFAULT_COUNTRY) -> str:
    """Normalize phone number to E.164 format.

    Args:
        phone_input: Phone number in any format
        country: Country code for parsing (default: US)

    Returns:
        Phone number in E.164 format (e.g., "+15551234567")

    Raises:
        PhoneNumberError: If phone number is invalid
    """
    if not phone_input or not phone_input.strip():
        raise PhoneNumberError("Phone number cannot be empty")

    try:
        parsed = phonenumbers.parse(phone_input, country)

        if not phonenumbers.is_valid_number(parsed):
            raise PhoneNumberError(f"Invalid phone number: {phone_input}")

        if not phonenumbers.is_possible_number(parsed):
            raise PhoneNumberError(f"Impossible phone number: {phone_input}")

        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    except phonenumbers.NumberParseException as e:
        raise PhoneNumberError(f"Cannot parse phone number '{phone_input}': {e}") from e


def validate_phone_number(phone_input: str, country: str = DEFAULT_COUNTRY) -> bool:
    """Validate if a phone number is valid."""
    try:
        parsed = phonenumbers.parse(phone_input, country)
        return phonenumbers.is_valid_number(parsed) and phonenumbers.is_possible_number(parsed)
    except phonenumbers.NumberParseException:
        return False


def normalize_phone_safe(phone_input: str, country: str = DEFAULT_COUNTRY) -> str | None:
    """Safely normalize phone number, returning None on failure."""
    try:
        return normalize_phone_e164(phone_input, country)
    except PhoneNumberError:
        return None


def phone_lookup_variants(phone_input: str, country: str = DEFAULT_COUNTRY) -> list[str]:
    """Generate canonical format variants of a phone number for SQL IN-list lookup.

    Used to find a contact whose ``phone_number`` column may have been stored in any
    of the common formats (E.164, national, international, raw digits, etc.) without
    scanning every row in the workspace.

    Args:
        phone_input: Phone number in any format.
        country: Country code for parsing (default: US).

    Returns:
        Deduplicated list of string variants. The original ``phone_input`` is always
        included as the first variant. Returns ``[phone_input]`` (or ``[]`` for
        empty input) when the number cannot be parsed.
    """
    variants: list[str] = []
    seen: set[str] = set()

    def _add(value: str | None) -> None:
        if value and value not in seen:
            seen.add(value)
            variants.append(value)

    _add(phone_input)
    if not phone_input or not phone_input.strip():
        return variants

    try:
        parsed = phonenumbers.parse(phone_input, country)
    except phonenumbers.NumberParseException:
        return variants

    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
    international = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    rfc3966 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.RFC3966)

    _add(e164)
    _add(national)
    _add(international)
    _add(rfc3966)

    # Digit-only variants: full E.164 digits, national digits, and (for NANP)
    # the 10-digit form without country code.
    e164_digits = e164.lstrip("+")
    national_digits = "".join(c for c in national if c.isdigit())
    _add(e164_digits)
    _add(national_digits)

    country_code = str(parsed.country_code) if parsed.country_code else ""
    if country_code and e164_digits.startswith(country_code):
        subscriber_digits = e164_digits[len(country_code) :]
        if subscriber_digits:
            _add(subscriber_digits)

    return variants
