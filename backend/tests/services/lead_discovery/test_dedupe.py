"""Tests for the lead-discovery dedupe helpers.

The dedupe key is a workspace-deterministic 64-char hex hash of the strongest
identifier on the lead (phone > email > website > owner name). These tests pin
the normalization rules and the cross-facet collision guarantee so refactors
can't silently regress the unique constraint on ``lead_prospects``.
"""

from __future__ import annotations

from typing import Any

from app.services.lead_discovery.dedupe import (
    dedupe_key_for_email,
    dedupe_key_for_lead,
    dedupe_key_for_owner_name,
    dedupe_key_for_phone,
    dedupe_key_for_website,
    dedupe_raw_leads,
    extract_host,
    normalize_email_for_dedupe,
    normalize_owner_name_for_dedupe,
    normalize_phone_for_dedupe,
    normalize_website_host_for_dedupe,
)
from app.services.lead_discovery.types import RawLead


class TestNormalizePhone:
    def test_e164_passthrough(self) -> None:
        # +1 202-555-01XX is the NANP fictional-use range — always valid.
        assert normalize_phone_for_dedupe("+12025550100") == "+12025550100"

    def test_us_national_normalizes_to_e164(self) -> None:
        assert normalize_phone_for_dedupe("(202) 555-0100") == "+12025550100"

    def test_dashes_and_dots_normalize_to_e164(self) -> None:
        assert normalize_phone_for_dedupe("202.555.0100") == "+12025550100"

    def test_none_returns_none(self) -> None:
        assert normalize_phone_for_dedupe(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_phone_for_dedupe("   ") is None

    def test_unparseable_returns_none(self) -> None:
        assert normalize_phone_for_dedupe("not-a-number") is None


class TestNormalizeEmail:
    def test_lowercases_and_trims(self) -> None:
        assert normalize_email_for_dedupe("  Foo@Bar.com  ") == "foo@bar.com"

    def test_none_returns_none(self) -> None:
        assert normalize_email_for_dedupe(None) is None

    def test_empty_returns_none(self) -> None:
        assert normalize_email_for_dedupe("") is None
        assert normalize_email_for_dedupe("   ") is None


class TestExtractHost:
    def test_scheme_full_url(self) -> None:
        assert extract_host("https://www.example.com/foo") == "example.com"

    def test_no_scheme_bare_host(self) -> None:
        assert extract_host("example.com/path") == "example.com"

    def test_strips_www_prefix(self) -> None:
        assert extract_host("https://www.example.com") == "example.com"

    def test_preserves_subdomain(self) -> None:
        assert extract_host("https://shop.example.com") == "shop.example.com"

    def test_lowercases_host(self) -> None:
        assert extract_host("https://Example.COM/About") == "example.com"

    def test_none_returns_none(self) -> None:
        assert extract_host(None) is None

    def test_empty_returns_none(self) -> None:
        assert extract_host("") is None
        assert extract_host("   ") is None

    def test_normalize_website_host_is_extract_host(self) -> None:
        # Public alias exists for symmetry with the other normalize_* helpers.
        assert normalize_website_host_for_dedupe("https://www.example.com") == extract_host(
            "https://www.example.com"
        )


class TestNormalizeOwnerName:
    def test_collapses_whitespace(self) -> None:
        assert normalize_owner_name_for_dedupe("  John   Doe  ") == "john doe"

    def test_strips_punctuation(self) -> None:
        assert normalize_owner_name_for_dedupe("John P. O'Brien-Jr.") == "john p obrienjr"

    def test_lowercases(self) -> None:
        assert normalize_owner_name_for_dedupe("JOHN DOE") == "john doe"

    def test_none_returns_none(self) -> None:
        assert normalize_owner_name_for_dedupe(None) is None

    def test_empty_returns_none(self) -> None:
        assert normalize_owner_name_for_dedupe("") is None
        assert normalize_owner_name_for_dedupe("   ") is None


class TestDedupeKeyPerFacet:
    """Each per-facet builder returns a 64-char hex digest or ``None``."""

    def test_phone_key_is_64_hex_chars(self) -> None:
        key = dedupe_key_for_phone("+12025550100")
        assert key is not None
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_phone_key_is_format_invariant(self) -> None:
        a = dedupe_key_for_phone("+12025550100")
        b = dedupe_key_for_phone("(202) 555-0100")
        c = dedupe_key_for_phone("202.555.0100")
        assert a is not None
        assert a == b == c

    def test_phone_key_none_when_unparseable(self) -> None:
        assert dedupe_key_for_phone(None) is None
        assert dedupe_key_for_phone("") is None
        assert dedupe_key_for_phone("not-a-number") is None

    def test_email_key_is_case_invariant(self) -> None:
        a = dedupe_key_for_email("Foo@Bar.com")
        b = dedupe_key_for_email("foo@bar.com")
        c = dedupe_key_for_email("  FOO@BAR.COM  ")
        assert a is not None
        assert a == b == c

    def test_email_key_none_when_missing(self) -> None:
        assert dedupe_key_for_email(None) is None
        assert dedupe_key_for_email("") is None

    def test_website_key_strips_scheme_www_and_path(self) -> None:
        a = dedupe_key_for_website("https://www.example.com/about")
        b = dedupe_key_for_website("http://example.com")
        c = dedupe_key_for_website("example.com/contact")
        assert a is not None
        assert a == b == c

    def test_website_key_none_when_missing(self) -> None:
        assert dedupe_key_for_website(None) is None
        assert dedupe_key_for_website("") is None

    def test_owner_key_is_normalization_invariant(self) -> None:
        a = dedupe_key_for_owner_name("John Doe")
        b = dedupe_key_for_owner_name("  john   doe  ")
        c = dedupe_key_for_owner_name("JOHN, DOE!")
        assert a is not None
        assert a == b == c

    def test_owner_key_none_when_missing(self) -> None:
        assert dedupe_key_for_owner_name(None) is None
        assert dedupe_key_for_owner_name("   ") is None


class TestFacetCollisionGuard:
    """A literal value must never collide across two identifier kinds."""

    def test_phone_and_email_with_same_literal_differ(self) -> None:
        # Hypothetical collision: the same string used as phone and email
        # must hash to different keys because of the facet prefix.
        literal = "2025550100"
        phone_key = dedupe_key_for_phone(literal)
        email_key = dedupe_key_for_email(literal)
        assert phone_key is not None
        assert email_key is not None
        assert phone_key != email_key

    def test_email_and_website_with_same_literal_differ(self) -> None:
        literal = "example.com"
        email_key = dedupe_key_for_email(literal)
        website_key = dedupe_key_for_website(literal)
        assert email_key is not None
        assert website_key is not None
        assert email_key != website_key

    def test_website_and_owner_with_same_literal_differ(self) -> None:
        literal = "John Doe"
        website_key = dedupe_key_for_website(literal)
        owner_key = dedupe_key_for_owner_name(literal)
        assert owner_key is not None
        # Website may parse "John Doe" into a host or return None; whichever
        # branch fires, the owner facet's key must not equal it.
        assert website_key != owner_key


class TestDedupeKeyForLead:
    """``dedupe_key_for_lead`` walks the priority list phone>email>web>owner."""

    def _lead(self, **overrides: Any) -> RawLead:
        defaults: dict[str, Any] = {"source_type": "google_places"}
        defaults.update(overrides)
        return RawLead(**defaults)

    def test_phone_wins_over_other_identifiers(self) -> None:
        lead = self._lead(
            phone_number="+12025550100",
            email="other@example.com",
            website="https://example.com",
            full_name="John Doe",
        )
        assert dedupe_key_for_lead(lead) == dedupe_key_for_phone("+12025550100")

    def test_email_used_when_no_phone(self) -> None:
        lead = self._lead(
            email="founder@example.com",
            website="https://example.com",
            full_name="Jane Roe",
        )
        assert dedupe_key_for_lead(lead) == dedupe_key_for_email("founder@example.com")

    def test_website_host_used_when_no_phone_or_email(self) -> None:
        lead = self._lead(website="https://www.example.com/contact")
        assert dedupe_key_for_lead(lead) == dedupe_key_for_website("https://www.example.com")

    def test_precomputed_website_host_used(self) -> None:
        # If the provider supplies a host but no URL we still get a key.
        lead = self._lead(website_host="example.com")
        assert dedupe_key_for_lead(lead) == dedupe_key_for_website("example.com")

    def test_full_name_used_when_only_owner_known(self) -> None:
        lead = self._lead(full_name="John Doe")
        assert dedupe_key_for_lead(lead) == dedupe_key_for_owner_name("John Doe")

    def test_first_last_combined_when_full_name_missing(self) -> None:
        lead = self._lead(first_name="John", last_name="Doe")
        assert dedupe_key_for_lead(lead) == dedupe_key_for_owner_name("John Doe")

    def test_returns_none_when_no_identifiers(self) -> None:
        lead = self._lead(name="Empty Co")  # name is not an identifier
        assert dedupe_key_for_lead(lead) is None

    def test_unparseable_phone_falls_through_to_email(self) -> None:
        lead = self._lead(phone_number="garbage", email="hi@example.com")
        assert dedupe_key_for_lead(lead) == dedupe_key_for_email("hi@example.com")


class TestDedupeRawLeads:
    """Batch dedupe preserves order and drops only later-seen duplicates."""

    def _lead(self, **overrides: Any) -> RawLead:
        defaults: dict[str, Any] = {"source_type": "google_places"}
        defaults.update(overrides)
        return RawLead(**defaults)

    def test_empty_input(self) -> None:
        unique, dup_count = dedupe_raw_leads([])
        assert unique == ()
        assert dup_count == 0

    def test_no_duplicates_passthrough(self) -> None:
        leads = [
            self._lead(phone_number="+12025550100", name="A"),
            self._lead(phone_number="+12025550200", name="B"),
        ]
        unique, dup_count = dedupe_raw_leads(leads)
        assert len(unique) == 2
        assert dup_count == 0
        assert [lead.name for lead in unique] == ["A", "B"]

    def test_duplicate_phone_format_variant_collapsed(self) -> None:
        leads = [
            self._lead(phone_number="+12025550100", name="First"),
            self._lead(phone_number="(202) 555-0100", name="Second"),
        ]
        unique, dup_count = dedupe_raw_leads(leads)
        assert dup_count == 1
        assert len(unique) == 1
        # Earliest occurrence wins.
        assert unique[0].name == "First"

    def test_leads_without_keys_are_kept(self) -> None:
        # Two leads with no identifier — both should survive (NULL dedupe key
        # is treated as distinct by Postgres' unique index).
        leads = [
            self._lead(name="Anon 1"),
            self._lead(name="Anon 2"),
        ]
        unique, dup_count = dedupe_raw_leads(leads)
        assert len(unique) == 2
        assert dup_count == 0

    def test_mixed_keyed_and_keyless(self) -> None:
        leads = [
            self._lead(phone_number="+12025550100", name="Phone A"),
            self._lead(name="Anon"),
            self._lead(phone_number="202-555-0100", name="Phone B"),
            self._lead(email="hi@example.com", name="Email A"),
        ]
        unique, dup_count = dedupe_raw_leads(leads)
        assert dup_count == 1
        assert [lead.name for lead in unique] == ["Phone A", "Anon", "Email A"]
