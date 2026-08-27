"""Deterministic SMS booking-confirmation recognition."""

import re
from typing import Any

_EXPLICIT_CONFIRMATION_RE = re.compile(
    r"\A\s*(?:yes(?:\s+please)?|yep|yeah|correct|confirm(?:ed)?|"
    r"that(?:'s| is) correct|looks good|sounds good|works for me|ok(?:ay)?)\s*[.!]?\s*\Z",
    re.IGNORECASE,
)
_CANONICAL_SUMMARY_PREFIX = "Please confirm:"
_CANONICAL_SUMMARY_SUFFIX = "Is that correct?"


def is_explicit_booking_confirmation(message: str) -> bool:
    """Return whether one reply unambiguously affirms the preceding summary."""
    return _EXPLICIT_CONFIRMATION_RE.fullmatch(message) is not None


def is_booking_confirmation_turn(messages: list[dict[str, Any]]) -> bool:
    """Return whether the newest turn explicitly affirms our canonical summary."""
    if len(messages) < 2:
        return False
    summary, reply = messages[-2:]
    summary_text = summary.get("content")
    reply_text = reply.get("content")
    return bool(
        summary.get("role") == "assistant"
        and isinstance(summary_text, str)
        and summary_text.startswith(_CANONICAL_SUMMARY_PREFIX)
        and summary_text.endswith(_CANONICAL_SUMMARY_SUFFIX)
        and reply.get("role") == "user"
        and isinstance(reply_text, str)
        and is_explicit_booking_confirmation(reply_text)
    )
