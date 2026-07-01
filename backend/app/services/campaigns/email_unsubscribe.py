"""Stateless signed tokens for one-click email unsubscribe links.

Marketing email must carry a working unsubscribe mechanism (CAN-SPAM). Rather
than store a per-recipient token column, the unsubscribe link embeds the
``campaign_contact`` id signed with an HMAC over ``settings.secret_key``. The
public endpoint verifies the signature before honoring the opt-out, so links
cannot be forged or enumerated.
"""

from __future__ import annotations

import base64
import hmac
import uuid
from hashlib import sha256

from app.core.config import settings

_SEP = "."


def _sign(payload: str) -> str:
    digest = hmac.new(settings.secret_key.encode(), payload.encode(), sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_unsubscribe_token(campaign_contact_id: uuid.UUID) -> str:
    """Return a signed, URL-safe token identifying one campaign enrollment."""
    payload = base64.urlsafe_b64encode(campaign_contact_id.bytes).decode().rstrip("=")
    return f"{payload}{_SEP}{_sign(payload)}"


def verify_unsubscribe_token(token: str) -> uuid.UUID | None:
    """Return the campaign_contact id if the token is valid, else ``None``."""
    try:
        payload, signature = token.split(_SEP, 1)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    try:
        padded = payload + "=" * (-len(payload) % 4)
        return uuid.UUID(bytes=base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        return None


def build_unsubscribe_url(campaign_contact_id: uuid.UUID) -> str | None:
    """Build the public unsubscribe URL for a campaign enrollment.

    Returns ``None`` when no public frontend origin is configured, so callers
    simply omit the footer rather than emit a broken link.
    """
    base = (settings.frontend_url or "").rstrip("/")
    if not base:
        return None
    token = make_unsubscribe_token(campaign_contact_id)
    return f"{base}/api/v1/email/unsubscribe?token={token}"
