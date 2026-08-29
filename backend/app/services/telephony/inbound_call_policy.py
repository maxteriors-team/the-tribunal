"""Deterministic caller notices and bounded Telnyx client-state markers."""

from __future__ import annotations

import base64
import binascii
import uuid
from typing import Literal

DISCLOSURE_VERSION = "inbound-ai-transcription-v1"
DISCLOSURE_TEXT = (
    "You are speaking with {business_name}'s AI assistant. "
    "This call will be transcribed to help with your request. "
    "By continuing, you agree to that processing."
)
BUSY_NOTICE_TEXT = "We're receiving too many calls from this number. Please try again later."
UNAVAILABLE_NOTICE_TEXT = "We're unable to connect your call right now. Please try again later."

InboundTerminalNotice = Literal["busy", "unavailable"]
_DISCLOSURE_STATE_PREFIX = f"inbound-disclosure:{DISCLOSURE_VERSION}:"
_TERMINAL_STATE_PREFIX = "inbound-terminal:v1:"
_MAX_CLIENT_STATE_LENGTH = 256


def build_inbound_disclosure(business_name: str | None) -> str:
    """Render fixed disclosure copy with only the tenant display name varying."""
    safe_name = "this business"
    if business_name:
        candidate = " ".join(business_name.split())[:120]
        if candidate:
            safe_name = candidate
    return DISCLOSURE_TEXT.format(business_name=safe_name)


def encode_inbound_disclosure_state(message_id: uuid.UUID) -> str:
    """Bind a disclosure command to one persisted inbound message."""
    return _encode_state(f"{_DISCLOSURE_STATE_PREFIX}{message_id}")


def decode_inbound_disclosure_state(client_state: object) -> uuid.UUID | None:
    """Return the bound message ID only for this feature's valid marker."""
    decoded = _decode_state(client_state)
    if decoded is None or not decoded.startswith(_DISCLOSURE_STATE_PREFIX):
        return None
    raw_message_id = decoded.removeprefix(_DISCLOSURE_STATE_PREFIX)
    try:
        message_id = uuid.UUID(raw_message_id)
    except ValueError:
        return None
    return message_id if str(message_id) == raw_message_id else None


def encode_inbound_terminal_state(notice: InboundTerminalNotice) -> str:
    """Mark a terminal notice so its completion can safely hang up the call."""
    return _encode_state(f"{_TERMINAL_STATE_PREFIX}{notice}")


def decode_inbound_terminal_state(client_state: object) -> InboundTerminalNotice | None:
    """Recognize only the two bounded terminal-notice states we emit."""
    decoded = _decode_state(client_state)
    if decoded == f"{_TERMINAL_STATE_PREFIX}busy":
        return "busy"
    if decoded == f"{_TERMINAL_STATE_PREFIX}unavailable":
        return "unavailable"
    return None


def _encode_state(value: str) -> str:
    return base64.b64encode(value.encode("ascii")).decode("ascii")


def _decode_state(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > _MAX_CLIENT_STATE_LENGTH:
        return None
    try:
        return base64.b64decode(value, validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError):
        return None
