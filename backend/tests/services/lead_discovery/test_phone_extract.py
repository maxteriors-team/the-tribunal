"""Tests for pure phone-number extraction from web pages."""

from __future__ import annotations

from app.services.lead_discovery.phone_extract import extract_phone_candidates


class TestExtractPhoneCandidates:
    def test_tel_link_is_high_confidence(self) -> None:
        html = '<a href="tel:+1-415-555-0132">Call us</a>'
        candidates = extract_phone_candidates(html, "https://acme.com/contact")
        assert candidates
        top = candidates[0]
        assert top.phone == "+14155550132"
        assert top.source == "tel_link"
        assert top.source_url == "https://acme.com/contact"
        assert top.confidence == 85

    def test_text_number_via_matcher(self) -> None:
        html = "<p>Reach our office at (415) 555-0132 during business hours.</p>"
        candidates = extract_phone_candidates(html)
        assert [c.phone for c in candidates] == ["+14155550132"]
        assert candidates[0].source == "page_text"

    def test_invalid_numbers_are_dropped(self) -> None:
        html = '<a href="tel:12345">bad</a><p>not a phone 999</p>'
        assert extract_phone_candidates(html) == []

    def test_dedupes_by_e164_keeping_highest_confidence(self) -> None:
        # Same number as both a tel: link and in the page text.
        html = '<a href="tel:+14155550132">Call</a><p>Or dial (415) 555-0132 anytime.</p>'
        candidates = extract_phone_candidates(html)
        assert len(candidates) == 1
        assert candidates[0].phone == "+14155550132"
        # tel: link wins on confidence.
        assert candidates[0].source == "tel_link"
        assert candidates[0].confidence == 85

    def test_descending_confidence_ordering(self) -> None:
        html = '<a href="tel:+14155550132">Call</a><p>Sales fax: (628) 555-0188.</p>'
        candidates = extract_phone_candidates(html)
        confs = [c.confidence for c in candidates]
        assert confs == sorted(confs, reverse=True)
        assert candidates[0].source == "tel_link"

    def test_empty_html_returns_empty(self) -> None:
        assert extract_phone_candidates("") == []
        assert extract_phone_candidates("<html><body></body></html>") == []

    def test_country_parsing_for_non_us(self) -> None:
        html = "<p>Call +44 20 7946 0958 in London.</p>"
        candidates = extract_phone_candidates(html, default_country="GB")
        assert candidates
        assert candidates[0].phone == "+442079460958"
