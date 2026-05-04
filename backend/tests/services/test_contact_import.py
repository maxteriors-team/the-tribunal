"""Tests for contact CSV import service.

Tests pure Python functions: CSV parsing, field mapping, validation,
and row processing — no database or external services required.
"""


from app.services.contacts.contact_import import (
    CONTACT_FIELDS,
    CSV_FIELD_MAPPING,
    VALID_STATUSES,
    ImportErrorDetail,
    ImportResult,
    clean_phone_number,
    find_csv_column,
    validate_email,
)


class TestFindCsvColumn:
    """Tests for find_csv_column helper."""

    def test_exact_match(self) -> None:
        """Exact header name returns itself."""
        result = find_csv_column(["first_name", "email", "phone"], "first_name")
        assert result == "first_name"

    def test_case_insensitive_match(self) -> None:
        """Match is case-insensitive."""
        result = find_csv_column(["First Name", "Email"], "first_name")
        assert result == "First Name"

    def test_alias_match(self) -> None:
        """Alias names in mapping are recognized."""
        # "firstname" is an alias for "first_name"
        result = find_csv_column(["firstname", "mobile"], "first_name")
        assert result == "firstname"

    def test_phone_aliases(self) -> None:
        """Phone field aliases: 'mobile', 'cell', 'telephone' all map."""
        for alias in ("mobile", "cell", "telephone", "phone"):
            result = find_csv_column([alias], "phone_number")
            assert result == alias, f"Expected '{alias}' to match phone_number"

    def test_no_match_returns_none(self) -> None:
        """No matching column returns None."""
        result = find_csv_column(["foo", "bar", "baz"], "first_name")
        assert result is None

    def test_empty_headers_returns_none(self) -> None:
        """Empty headers list returns None."""
        result = find_csv_column([], "first_name")
        assert result is None

    def test_returns_original_case(self) -> None:
        """Returns the original header casing from the CSV."""
        result = find_csv_column(["PHONE NUMBER"], "phone_number")
        assert result == "PHONE NUMBER"


class TestValidateEmail:
    """Tests for validate_email helper."""

    def test_valid_email(self) -> None:
        """Valid email addresses return True."""
        assert validate_email("user@example.com") is True
        assert validate_email("user.name+tag@sub.domain.org") is True

    def test_empty_string_is_valid(self) -> None:
        """Empty string is treated as absent (valid)."""
        assert validate_email("") is True

    def test_invalid_no_at(self) -> None:
        """Email without @ is invalid."""
        assert validate_email("notanemail") is False

    def test_invalid_no_domain(self) -> None:
        """Email with no domain is invalid."""
        assert validate_email("user@") is False

    def test_invalid_no_tld(self) -> None:
        """Email with no TLD is invalid."""
        assert validate_email("user@domain") is False


class TestCleanPhoneNumber:
    """Tests for clean_phone_number helper."""

    def test_empty_string_returns_none(self) -> None:
        """Empty phone returns None."""
        assert clean_phone_number("") is None

    def test_too_short_returns_none(self) -> None:
        """Phone with fewer than 10 digits returns None."""
        assert clean_phone_number("123") is None

    def test_valid_us_number(self) -> None:
        """Valid US number normalizes correctly."""
        result = clean_phone_number("4155551234")
        assert result is not None
        assert len(result) >= 10

    def test_formatted_number_cleaned(self) -> None:
        """Formatting characters are stripped before length check."""
        # "(415) 555-1234" → "+14155551234"
        result = clean_phone_number("(415) 555-1234")
        assert result is not None

    def test_e164_format_preserved(self) -> None:
        """E.164 format is accepted."""
        result = clean_phone_number("+14155551234")
        assert result is not None


class TestImportDataclasses:
    """Tests for ImportErrorDetail and ImportResult dataclasses."""

    def test_import_error_detail_defaults(self) -> None:
        """ImportErrorDetail has correct defaults."""
        err = ImportErrorDetail(row=3)
        assert err.row == 3
        assert err.field is None
        assert err.error == ""

    def test_import_error_detail_full(self) -> None:
        """ImportErrorDetail accepts all fields."""
        err = ImportErrorDetail(row=5, field="email", error="Invalid email format")
        assert err.field == "email"
        assert err.error == "Invalid email format"

    def test_import_result_defaults(self) -> None:
        """ImportResult has correct defaults."""
        result = ImportResult()
        assert result.total_rows == 0
        assert result.successful == 0
        assert result.failed == 0
        assert result.skipped_duplicates == 0
        assert result.errors == []
        assert result.created_contacts == []

    def test_import_result_accumulation(self) -> None:
        """ImportResult fields can be incremented."""
        result = ImportResult()
        result.total_rows = 10
        result.successful = 8
        result.failed = 2
        result.errors.append(ImportErrorDetail(row=3, error="bad phone"))
        assert result.successful == 8
        assert len(result.errors) == 1


class TestCsvFieldMapping:
    """Tests for CSV_FIELD_MAPPING constants."""

    def test_all_required_fields_present(self) -> None:
        """All contact fields have entries in the mapping."""
        required_fields = {"first_name", "last_name", "email", "phone_number", "company_name"}
        for field in required_fields:
            assert field in CSV_FIELD_MAPPING, f"Missing mapping for {field}"

    def test_valid_statuses_set(self) -> None:
        """VALID_STATUSES contains expected values."""
        expected = {"new", "contacted", "qualified", "converted", "lost"}
        assert expected == VALID_STATUSES

    def test_contact_fields_structure(self) -> None:
        """CONTACT_FIELDS entries have required keys."""
        for field_def in CONTACT_FIELDS:
            assert "name" in field_def
            assert "label" in field_def
            assert "required" in field_def

    def test_required_contact_fields(self) -> None:
        """first_name and phone_number are marked as required."""
        required = {f["name"] for f in CONTACT_FIELDS if f["required"]}
        assert "first_name" in required
        assert "phone_number" in required
