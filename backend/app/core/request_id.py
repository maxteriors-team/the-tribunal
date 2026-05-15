"""Request ID utilities.

A request ID is a short, sortable correlation identifier that travels with a
single HTTP request from edge → app → logs. We accept caller-supplied IDs via
the ``X-Request-ID`` header (so upstream proxies, load balancers, or browser
extensions can stitch traces together), and otherwise generate a fresh
`ULID <https://github.com/ulid/spec>`_.

ULIDs are preferred over UUIDv4 here because they're:

* **Lexicographically sortable** — the leading 48 bits encode the millisecond
  timestamp, so log lines/IDs sort chronologically without extra fields.
* **Compact** — 26 chars of Crockford base32 vs. 36 chars of UUID hyphen form.
* **URL/header safe** — no hyphens, no padding, case-insensitive.

The implementation is intentionally self-contained (no new runtime dependency).
"""

from __future__ import annotations

import os
import time

# Crockford base32 alphabet (excludes I, L, O, U to avoid visual ambiguity).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# Max length of a caller-supplied request ID we'll accept. Anything longer is
# replaced with a freshly generated ULID to keep log lines / response headers
# bounded and prevent header-smuggling abuse.
MAX_REQUEST_ID_LENGTH = 128

# Allowed characters in a caller-supplied request ID: alphanumerics and a small
# set of separators commonly used by tracing frameworks. Everything else is
# rejected and we generate a fresh ULID instead.
_ALLOWED_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_."
)


def generate_ulid() -> str:
    """Generate a 26-character ULID.

    Format: 48-bit millisecond timestamp + 80-bit randomness, encoded as
    Crockford base32. Two ULIDs minted in the same millisecond are
    distinguished only by their random payload — collision probability per
    millisecond is 2^-80, which is fine for request correlation.
    """
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    randomness = int.from_bytes(os.urandom(10), "big")  # 80 bits
    value = (timestamp_ms << 80) | randomness

    chars: list[str] = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def sanitize_request_id(raw: str | None) -> str:
    """Return a safe request ID, generating a fresh ULID if ``raw`` is unusable.

    A caller-supplied ID is accepted only if it's non-empty, within length
    limits, and uses a conservative character whitelist. Otherwise we fall
    back to a freshly generated ULID so the rest of the request pipeline can
    rely on every request having exactly one correlation ID.
    """
    if not raw:
        return generate_ulid()
    raw = raw.strip()
    if not raw or len(raw) > MAX_REQUEST_ID_LENGTH:
        return generate_ulid()
    if not all(ch in _ALLOWED_CHARS for ch in raw):
        return generate_ulid()
    return raw
