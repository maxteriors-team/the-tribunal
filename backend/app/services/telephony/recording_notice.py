"""Spoken "this call is recorded" notice, and the state binding it to a call.

Recording a two-party phone call is only safe when every party knows it is
happening: a dozen-odd US states require all-party consent, and a home-service
workspace calls homeowners wherever they live. So no call in this system starts
recording until this notice has actually been *spoken* on the leg.

The notice is played with Telnyx ``speak`` carrying a ``client_state`` minted
here. Telnyx echoes that state on ``call.speak.ended``, which is the only signal
that the words really reached the caller — so recording starts there, never
before. If the speak command fails, the call continues and recording simply does
not start: a missing recording is recoverable, an undisclosed one is not.
"""

from __future__ import annotations

import base64
import binascii
import uuid

# Fixed copy. The workspace's own business name is deliberately absent: the
# notice is about *this* call being recorded, and the caller already knows who
# they are talking to (outbound AI calls greet them, operator calls are humans).
RECORDING_NOTICE_TEXT = "Just so you know, this call is recorded."

_RECORDING_NOTICE_STATE_PREFIX = "recording-notice:v1:"
_MAX_CLIENT_STATE_LENGTH = 256


def encode_recording_notice_state(message_id: uuid.UUID) -> str:
    """Bind a spoken notice to the one call message it authorises recording for."""
    return _encode_state(f"{_RECORDING_NOTICE_STATE_PREFIX}{message_id}")


def decode_recording_notice_state(client_state: object) -> uuid.UUID | None:
    """Return the bound message ID only for this feature's valid marker.

    ``client_state`` comes back from the provider, so it is untrusted input:
    anything that is not our own exact marker plus a canonical UUID returns
    ``None`` rather than authorising a recording.
    """
    decoded = _decode_state(client_state)
    if decoded is None or not decoded.startswith(_RECORDING_NOTICE_STATE_PREFIX):
        return None
    raw_message_id = decoded.removeprefix(_RECORDING_NOTICE_STATE_PREFIX)
    try:
        message_id = uuid.UUID(raw_message_id)
    except ValueError:
        return None
    return message_id if str(message_id) == raw_message_id else None


def _encode_state(value: str) -> str:
    return base64.b64encode(value.encode("ascii")).decode("ascii")


def _decode_state(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > _MAX_CLIENT_STATE_LENGTH:
        return None
    try:
        return base64.b64decode(value, validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError):
        return None
