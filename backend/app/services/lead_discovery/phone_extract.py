"""Pure phone-number extraction for the phone-reveal flow.

Unlike email, a phone number **cannot be inferred** from a person's name — there
is no deterministic pattern from identity to digits. So this module does the only
realistic no-paid-API thing: it parses a company web page's markup and pulls the
phone numbers that are already published on it (a business / main line, rarely a
personal direct dial).

Two signal tiers, mirroring the confidence shape of :mod:`email_patterns`:

* **High** — ``a[href^="tel:"]`` anchors: an explicitly published call link.
* **Medium** — numbers found in the page's visible text via
  :class:`phonenumbers.PhoneNumberMatcher`.

Every candidate is normalized to E.164 and dropped unless it passes
:func:`validate_phone_number`. This module performs **no** I/O — crawling lives in
:mod:`phone_finder`.
"""

from __future__ import annotations

from dataclasses import dataclass

import phonenumbers
from bs4 import BeautifulSoup

from app.utils.phone import normalize_phone_safe, validate_phone_number

# Confidence weights per source tier (0..100).
_TEL_LINK_CONFIDENCE = 85
_TEXT_MATCH_CONFIDENCE = 55


@dataclass(slots=True, frozen=True)
class PhoneCandidate:
    """One ranked candidate phone number scraped from a company page."""

    phone: str  # E.164, e.g. "+15551234567"
    source: str  # "tel_link" | "page_text"
    confidence: int  # 0..100
    source_url: str | None = None


def extract_phone_candidates(
    html: str,
    source_url: str | None = None,
    default_country: str = "US",
) -> list[PhoneCandidate]:
    """Extract ranked candidate phone numbers from a web page (pure).

    Parses ``tel:`` links (high confidence) and visible-text numbers (medium
    confidence), normalizes each to E.164, drops anything that fails validation,
    de-duplicates by E.164 keeping the highest confidence, and returns the list
    in descending confidence order. Returns an empty list on empty/invalid HTML.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001 - never let parsing crash the reveal flow
        return []

    best: dict[str, PhoneCandidate] = {}

    def _add(raw: str, source: str, confidence: int) -> None:
        e164 = normalize_phone_safe(raw, default_country)
        if not e164 or not validate_phone_number(e164, default_country):
            return
        existing = best.get(e164)
        if existing is None or confidence > existing.confidence:
            best[e164] = PhoneCandidate(
                phone=e164,
                source=source,
                confidence=confidence,
                source_url=source_url,
            )

    # High-confidence: explicit tel: links.
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if href.lower().startswith("tel:"):
            _add(href[4:], "tel_link", _TEL_LINK_CONFIDENCE)

    # Medium-confidence: numbers in the page's visible text.
    text = soup.get_text(" ")
    for match in phonenumbers.PhoneNumberMatcher(text, default_country):
        e164 = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
        _add(e164, "page_text", _TEXT_MATCH_CONFIDENCE)

    return sorted(best.values(), key=lambda c: c.confidence, reverse=True)
