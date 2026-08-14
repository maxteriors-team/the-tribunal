"""Pure helpers for validating and labeling customer-facing meeting URLs."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_ZOOM_JOIN_PATH = re.compile(r"^/j/(?P<meeting_id>[0-9]+)/*$")


def zoom_meeting_id_from_url(value: str | None) -> str | None:
    """Return a Zoom meeting ID only for a canonical HTTPS Zoom join URL."""
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or (hostname != "zoom.us" and not hostname.endswith(".zoom.us"))
    ):
        return None
    match = _ZOOM_JOIN_PATH.fullmatch(parsed.path)
    return match.group("meeting_id") if match else None


def meeting_provider_name(value: str | None) -> str:
    """Return safe customer-facing provider copy for a meeting URL."""
    if zoom_meeting_id_from_url(value):
        return "Zoom"
    if value:
        try:
            parsed = urlsplit(value)
        except ValueError:
            parsed = None
        if (
            parsed
            and parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and (parsed.hostname or "").casefold() == "meet.google.com"
        ):
            return "Google Meet"
    return "video meeting"
