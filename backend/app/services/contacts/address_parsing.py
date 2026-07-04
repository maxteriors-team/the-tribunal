"""Best-effort parsing of free-form US addresses into contact columns.

Public lead forms (quote funnels on customer websites) collect the property
address as one free-form string — usually Google-formatted like
``"14040 Pernell Dr, Sterling Heights, MI 48313, USA"`` when the funnel ran a
satellite measurement, or hand-typed like ``"32044 Holly Dr."`` when it
didn't. The CRM stores addresses in structured columns
(``address_line1``/``city``/``state``/``zip``), so this module bridges the two.

Parsing is deliberately conservative: only the unambiguous
``street, city, ST zip`` shapes are split. Anything else lands whole in
``address_line1`` — a lead's address must never be mangled or dropped just
because it didn't match a pattern.
"""

import re
from dataclasses import dataclass

# "street, city, ST 48313[-1234][, USA|United States]" — the shape Google
# Maps / Places produces. State must be exactly two letters; ZIP 5 or 5+4.
_FULL_ADDRESS_RE = re.compile(
    r"^(?P<line1>[^,]+?)\s*,\s*"
    r"(?P<city>[^,]+?)\s*,\s*"
    r"(?P<state>[A-Za-z]{2})\.?\s+"
    r"(?P<zip>\d{5}(?:-\d{4})?)"
    r"\s*(?:,\s*(?:USA|United States))?\s*$"
)

# "street, city, ST" — same but without a ZIP (hand-typed).
_NO_ZIP_ADDRESS_RE = re.compile(
    r"^(?P<line1>[^,]+?)\s*,\s*"
    r"(?P<city>[^,]+?)\s*,\s*"
    r"(?P<state>[A-Za-z]{2})\.?\s*$"
)

# "street, city, ST zip" with the last comma missing before the state —
# e.g. "12845 Culver Dr, Shelby Township MI 48315" (typed, no second comma).
_MISSING_COMMA_RE = re.compile(
    r"^(?P<line1>[^,]+?)\s*,\s*"
    r"(?P<city>.+?)\s+"
    r"(?P<state>[A-Za-z]{2})\.?\s+"
    r"(?P<zip>\d{5}(?:-\d{4})?)\s*$"
)


@dataclass(frozen=True)
class ParsedAddress:
    """Structured pieces of a free-form address; unparsed parts stay None."""

    line1: str
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None


def parse_us_address(raw: str) -> ParsedAddress | None:
    """Split a free-form US address into structured parts, conservatively.

    Returns ``None`` for empty/whitespace input. When no pattern matches,
    the whole (trimmed) string is returned as ``line1`` so nothing is lost.
    """
    text = " ".join(raw.split()).strip(" ,")
    if not text:
        return None

    for pattern in (_FULL_ADDRESS_RE, _MISSING_COMMA_RE, _NO_ZIP_ADDRESS_RE):
        if match := pattern.match(text):
            groups = match.groupdict()
            return ParsedAddress(
                line1=groups["line1"].strip(),
                city=groups["city"].strip(" ,"),
                state=groups["state"].upper(),
                zip_code=groups.get("zip"),
            )

    return ParsedAddress(line1=text)
