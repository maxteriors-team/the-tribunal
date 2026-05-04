"""Focused tests for ContactCreate, ContactUpdate, and QualificationSignalDetail.

These tests complement tests/schemas/test_contact_schemas.py by zeroing in on
field-level validation for create/update + QualificationSignalDetail defaults.
"""

import pytest
from pydantic import ValidationError

from app.schemas.contact import (
    ContactCreate,
    ContactUpdate,
    QualificationSignalDetail,
)


class TestContactCreateMinimal:
    """Minimal required-field validation."""

    def test_valid_minimal(self) -> None:
        """first_name + 10+ char phone_number is enough."""
        c = ContactCreate(first_name="Alice", phone_number="5551234567")
        assert c.first_name == "Alice"
        assert c.phone_number == "5551234567"
        assert c.status == "new"
        assert c.last_name is None
        assert c.email is None
        assert c.company_name is None
        assert c.tags is None
        assert c.notes is None
        assert c.source is None
        assert c.important_dates is None


class TestContactCreateFull:
    """Full field set validation."""

    def test_valid_full(self) -> None:
        """All fields accepted."""
        c = ContactCreate(
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
            phone_number="+15551234567",
            company_name="Acme",
            address_line1="1 Main St",
            address_line2="Apt 2",
            address_city="Springfield",
            address_state="IL",
            address_zip="62701",
            status="qualified",
            tags=["vip"],
            notes="hot lead",
            source="webform",
            important_dates={"birthday": "2000-01-01"},
        )
        assert c.last_name == "Smith"
        assert c.email == "alice@example.com"
        assert c.company_name == "Acme"
        assert c.address_city == "Springfield"
        assert c.tags == ["vip"]
        assert c.status == "qualified"
        assert c.important_dates == {"birthday": "2000-01-01"}


class TestContactCreateErrors:
    """Validation error paths."""

    def test_missing_first_name(self) -> None:
        """first_name is required."""
        with pytest.raises(ValidationError) as exc:
            ContactCreate.model_validate({"phone_number": "5551234567"})
        assert any(e["loc"] == ("first_name",) for e in exc.value.errors())

    def test_missing_phone_number(self) -> None:
        """phone_number is required."""
        with pytest.raises(ValidationError) as exc:
            ContactCreate.model_validate({"first_name": "Alice"})
        assert any(e["loc"] == ("phone_number",) for e in exc.value.errors())

    def test_empty_first_name(self) -> None:
        """Empty first_name fails min_length=1."""
        with pytest.raises(ValidationError):
            ContactCreate(first_name="", phone_number="5551234567")

    def test_first_name_too_long(self) -> None:
        """first_name > 100 chars fails max_length."""
        with pytest.raises(ValidationError):
            ContactCreate(first_name="A" * 101, phone_number="5551234567")

    def test_invalid_email(self) -> None:
        """Malformed email fails EmailStr validation."""
        with pytest.raises(ValidationError):
            ContactCreate(
                first_name="Alice",
                phone_number="5551234567",
                email="not-an-email",
            )

    def test_phone_too_short(self) -> None:
        """phone_number < 10 chars fails min_length."""
        with pytest.raises(ValidationError):
            ContactCreate(first_name="Alice", phone_number="123")

    def test_phone_too_long(self) -> None:
        """phone_number > 20 chars fails max_length."""
        with pytest.raises(ValidationError):
            ContactCreate(first_name="Alice", phone_number="1" * 21)

    def test_last_name_too_long(self) -> None:
        """last_name > 100 chars fails max_length."""
        with pytest.raises(ValidationError):
            ContactCreate(
                first_name="Alice",
                phone_number="5551234567",
                last_name="B" * 101,
            )


class TestContactUpdate:
    """ContactUpdate — all fields optional."""

    def test_all_none(self) -> None:
        """Empty update is valid."""
        u = ContactUpdate()
        assert u.first_name is None
        assert u.phone_number is None
        assert u.email is None
        assert u.lead_score is None

    def test_partial_update_first_name(self) -> None:
        """Partial update with first_name only."""
        u = ContactUpdate(first_name="Bob")
        assert u.first_name == "Bob"
        assert u.last_name is None

    def test_partial_update_lead_score(self) -> None:
        """Partial update with lead_score only."""
        u = ContactUpdate(lead_score=42)
        assert u.lead_score == 42

    def test_invalid_email(self) -> None:
        """Invalid email still fails on update."""
        with pytest.raises(ValidationError):
            ContactUpdate(email="not-an-email")

    def test_empty_first_name_still_fails(self) -> None:
        """Empty first_name on update fails min_length=1."""
        with pytest.raises(ValidationError):
            ContactUpdate(first_name="")

    def test_phone_too_short_on_update(self) -> None:
        """Phone min_length still enforced."""
        with pytest.raises(ValidationError):
            ContactUpdate(phone_number="12")


class TestQualificationSignalDetail:
    """QualificationSignalDetail defaults and construction."""

    def test_defaults(self) -> None:
        """Defaults: detected=False, value=None, confidence=0.0."""
        d = QualificationSignalDetail()
        assert d.detected is False
        assert d.value is None
        assert d.confidence == 0.0

    def test_full_construction(self) -> None:
        """All fields accepted."""
        d = QualificationSignalDetail(
            detected=True, value="100k budget", confidence=0.9
        )
        assert d.detected is True
        assert d.value == "100k budget"
        assert d.confidence == 0.9
