"""Signed tickets for the Telnyx media-stream WebSocket.

``/voice/stream/{call_id}`` carries live customer call audio and, once the
call context is resolved, runs against a tenant's own AI credentials. The
``call_id`` in that path is a Telnyx ``call_control_id`` — an identifier that
appears in webhook logs and in the stream URL itself, so it is emphatically
**not** a secret and must never be the only thing standing between the public
internet and a customer's call.

Telnyx dials the stream URL for us and cannot present a bearer header, so the
credential has to ride in the URL. We therefore mint a short-lived HMAC ticket
bound to the specific ``call_control_id`` and verify it *before* accepting the
socket.

Design notes:

* The ticket is keyed off ``settings.secret_key``, which is already required at
  boot with a minimum length and Shannon-entropy floor (see
  ``_validate_security_key`` in ``app.main``), so there is no weak-default path.
* Verification is constant-time (:func:`hmac.compare_digest`).
* The TTL only needs to span "Telnyx accepted the answer command" → "Telnyx
  opened the media socket", which is seconds. It deliberately does **not** need
  to cover call duration, because the ticket is checked once at handshake.
* Tickets are intentionally *not* single-use: Telnyx may retry a media
  connection, and rejecting a legitimate retry would drop a live customer call.
  The short TTL is the containment mechanism instead.
"""

import hashlib
import hmac
import time

from app.core.config import settings

#: Query-string parameter Telnyx will echo back to us on the media socket.
STREAM_TOKEN_PARAM = "token"

#: How long a freshly minted stream ticket stays valid. Generous enough to
#: absorb provider-side scheduling delay, short enough that a ticket scraped
#: from a log is useless by the time anyone reads it.
STREAM_TOKEN_TTL_SECONDS = 300

_DIGEST = hashlib.sha256


def _signature(call_control_id: str, expires_at: int) -> str:
    """Return the hex HMAC binding a call id to an expiry."""
    payload = f"{call_control_id}.{expires_at}".encode()
    return hmac.new(settings.secret_key.encode(), payload, _DIGEST).hexdigest()


def mint_stream_token(call_control_id: str, ttl_seconds: int | None = None) -> str:
    """Mint a short-lived ticket authorizing a media stream for ``call_control_id``.

    Args:
        call_control_id: Telnyx call control ID the ticket is bound to.
        ttl_seconds: Optional override for the default TTL.

    Returns:
        An opaque ``"<expiry>.<signature>"`` token safe for a URL query string.
    """
    ttl = STREAM_TOKEN_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    expires_at = int(time.time()) + ttl
    return f"{expires_at}.{_signature(call_control_id, expires_at)}"


def verify_stream_token(call_control_id: str, token: str | None) -> bool:
    """Verify a stream ticket against its call id and expiry.

    Fails closed on every malformed, expired, or mismatched input.

    Args:
        call_control_id: Call control ID from the WebSocket path.
        token: Ticket supplied on the WebSocket query string.

    Returns:
        ``True`` only when the ticket is well-formed, unexpired, and its
        signature matches ``call_control_id``.
    """
    if not token or not call_control_id:
        return False

    expiry_str, separator, signature = token.partition(".")
    if not separator or not signature:
        return False

    try:
        expires_at = int(expiry_str)
    except ValueError:
        return False

    if expires_at < int(time.time()):
        return False

    return hmac.compare_digest(signature, _signature(call_control_id, expires_at))
