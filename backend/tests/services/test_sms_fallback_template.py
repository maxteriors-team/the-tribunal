"""Tests for app.services.campaigns.sms_fallback.render_fallback_template.

Pure function tests — no DB. Uses a MagicMock for the Contact model.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.campaigns.sms_fallback import render_fallback_template


def make_contact(
    first_name: str | None = "Alice",
    last_name: str | None = "Smith",
    email: str | None = "alice@example.com",
    company_name: str | None = "Acme",
) -> Any:
    """Build a duck-typed Contact object using SimpleNamespace."""
    return SimpleNamespace(
        first_name=first_name,
        last_name=last_name,
        email=email,
        company_name=company_name,
    )


class TestRenderFallbackTemplatePlaceholders:
    """Tests for each individual placeholder."""

    def test_first_name_placeholder(self) -> None:
        """{first_name} is replaced."""
        contact = make_contact()
        result = render_fallback_template("Hi {first_name}", contact, "no_answer")
        assert result == "Hi Alice"

    def test_last_name_placeholder(self) -> None:
        """{last_name} is replaced."""
        contact = make_contact()
        result = render_fallback_template("Name: {last_name}", contact, "no_answer")
        assert result == "Name: Smith"

    def test_full_name_placeholder(self) -> None:
        """{full_name} combines first and last."""
        contact = make_contact()
        result = render_fallback_template("Hello {full_name}", contact, "no_answer")
        assert result == "Hello Alice Smith"

    def test_company_name_placeholder(self) -> None:
        """{company_name} is replaced."""
        contact = make_contact()
        result = render_fallback_template(
            "You work at {company_name}", contact, "no_answer"
        )
        assert result == "You work at Acme"

    def test_email_placeholder(self) -> None:
        """{email} is replaced."""
        contact = make_contact()
        result = render_fallback_template("Email: {email}", contact, "no_answer")
        assert result == "Email: alice@example.com"

    def test_call_outcome_placeholder(self) -> None:
        """{call_outcome} is replaced with raw outcome value."""
        contact = make_contact()
        result = render_fallback_template(
            "Outcome: {call_outcome}", contact, "busy"
        )
        assert result == "Outcome: busy"

    def test_call_reason_placeholder(self) -> None:
        """{call_reason} is replaced with friendly text."""
        contact = make_contact()
        result = render_fallback_template(
            "Reason: {call_reason}", contact, "no_answer"
        )
        assert result == "Reason: we tried calling but couldn't reach you"

    def test_multiple_placeholders(self) -> None:
        """Multiple placeholders in one template are all replaced."""
        contact = make_contact()
        template = "Hi {first_name} from {company_name}, {call_reason}."
        result = render_fallback_template(template, contact, "no_answer")
        assert result == (
            "Hi Alice from Acme, we tried calling but couldn't reach you."
        )


class TestRenderFallbackTemplateCallOutcomeMappings:
    """Tests for each outcome → friendly reason mapping."""

    @pytest.mark.parametrize(
        ("outcome", "expected"),
        [
            ("no_answer", "we tried calling but couldn't reach you"),
            ("busy", "your line was busy when we called"),
            ("voicemail", "we left a message but wanted to follow up"),
            ("rejected", "we tried calling earlier"),
            ("unknown", "we tried reaching you by phone"),
            ("", "we tried reaching you by phone"),
            ("something_else", "we tried reaching you by phone"),
        ],
    )
    def test_outcome_mapping(self, outcome: str, expected: str) -> None:
        """Each outcome maps to the correct friendly reason; unknown → default."""
        contact = make_contact()
        result = render_fallback_template("{call_reason}", contact, outcome)
        assert result == expected


class TestRenderFallbackTemplateNoneFields:
    """Contact with None fields should gracefully fall back to empty strings."""

    def test_all_none_fields(self) -> None:
        """Contact with all None fields produces empty replacements."""
        contact = make_contact(
            first_name=None, last_name=None, email=None, company_name=None
        )
        template = "[{first_name}][{last_name}][{full_name}][{email}][{company_name}]"
        result = render_fallback_template(template, contact, "no_answer")
        assert result == "[][][][][]"

    def test_only_first_name_set(self) -> None:
        """Only first_name populated, full_name uses just first."""
        contact = make_contact(
            first_name="Alice", last_name=None, email=None, company_name=None
        )
        result = render_fallback_template("{full_name}", contact, "no_answer")
        assert result == "Alice"

    def test_only_last_name_set(self) -> None:
        """Only last_name populated, full_name uses just last."""
        contact = make_contact(
            first_name=None, last_name="Smith", email=None, company_name=None
        )
        result = render_fallback_template("{full_name}", contact, "no_answer")
        assert result == "Smith"


class TestRenderFallbackTemplateCaseInsensitive:
    """Placeholder matching is case-insensitive."""

    def test_uppercase_placeholder(self) -> None:
        """{FIRST_NAME} is replaced (case-insensitive)."""
        contact = make_contact()
        result = render_fallback_template("Hi {FIRST_NAME}", contact, "no_answer")
        assert result == "Hi Alice"

    def test_mixed_case_placeholder(self) -> None:
        """{First_Name} is replaced."""
        contact = make_contact()
        result = render_fallback_template("Hi {First_Name}", contact, "no_answer")
        assert result == "Hi Alice"

    def test_mixed_case_full_name(self) -> None:
        """{Full_Name} is replaced."""
        contact = make_contact()
        result = render_fallback_template(
            "Hello {Full_Name}!", contact, "no_answer"
        )
        assert result == "Hello Alice Smith!"


class TestRenderFallbackTemplateEdgeCases:
    """Edge cases."""

    def test_no_placeholders(self) -> None:
        """Template with no placeholders passes through unchanged."""
        contact = make_contact()
        template = "Hello there! Just following up."
        result = render_fallback_template(template, contact, "no_answer")
        assert result == template

    def test_empty_template(self) -> None:
        """Empty template returns empty string."""
        contact = make_contact()
        assert render_fallback_template("", contact, "no_answer") == ""

    def test_unknown_placeholder_preserved(self) -> None:
        """Unknown placeholders are left as-is."""
        contact = make_contact()
        result = render_fallback_template(
            "Hi {unknown_placeholder}", contact, "no_answer"
        )
        assert result == "Hi {unknown_placeholder}"

    def test_same_placeholder_multiple_times(self) -> None:
        """Placeholder appearing multiple times is replaced every time."""
        contact = make_contact()
        result = render_fallback_template(
            "{first_name}, {first_name}, {first_name}", contact, "no_answer"
        )
        assert result == "Alice, Alice, Alice"
