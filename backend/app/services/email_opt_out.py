"""Contact-level email opt-out: the gate every commercial email passes through.

The product already had two narrower opt-outs and neither covered workflow mail:

* :class:`app.models.opt_out.GlobalOptOut` suppresses **SMS** by phone number
  (the STOP keyword), and
* :mod:`app.services.campaigns.email_unsubscribe` silences **one campaign
  enrollment**, keyed to a ``campaign_contact`` row.

An automation that emails someone every week is commercial mail with no
campaign enrollment behind it, so before this module there was no way for that
person to make it stop. This adds the missing contact-scoped opt-out and the
one function the send path calls to honour it.

Tokens reuse the HMAC-over-``secret_key`` scheme already used for campaign
unsubscribes: stateless, unforgeable, and not enumerable, so no per-recipient
token column is needed. The subject is the contact id rather than an enrollment
id, which is what makes one click silence *all* commercial mail to that person.

Not legal advice \u2014 an engineering control on the path that sends the mail.
"""

from __future__ import annotations

import base64
import hmac
from datetime import UTC, datetime
from hashlib import sha256

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.contact import Contact

__all__ = [
    "build_email_unsubscribe_url",
    "email_suppressed",
    "make_email_unsubscribe_token",
    "record_email_opt_out",
    "verify_email_unsubscribe_token",
]

logger = structlog.get_logger()

_SEP = "."
# Namespaced so a campaign-unsubscribe token can never be replayed against the
# contact-level endpoint (or the reverse) despite sharing a signing key.
_SCOPE = b"contact-email-unsub"


def _sign(payload: str) -> str:
    message = _SCOPE + payload.encode()
    digest = hmac.new(settings.secret_key.encode(), message, sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_email_unsubscribe_token(contact_id: int) -> str:
    """Return a signed, URL-safe token identifying one contact."""
    payload = base64.urlsafe_b64encode(str(contact_id).encode()).decode().rstrip("=")
    return f"{payload}{_SEP}{_sign(payload)}"


def verify_email_unsubscribe_token(token: str) -> int | None:
    """Return the contact id if the token is valid, else ``None``."""
    try:
        payload, signature = token.split(_SEP, 1)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    try:
        padded = payload + "=" * (-len(payload) % 4)
        return int(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


def build_email_unsubscribe_url(contact_id: int) -> str | None:
    """Build the public unsubscribe URL for a contact.

    Returns ``None`` when no public frontend origin is configured. Callers must
    treat that as "cannot send commercial mail" rather than "send without a
    footer" — a marketing email with a dead opt-out link is the failure this
    whole module exists to prevent, and ``FRONTEND_URL`` silently defaults to
    localhost in a misconfigured deploy.
    """
    base = (settings.frontend_url or "").rstrip("/")
    if not base:
        return None
    token = make_email_unsubscribe_token(contact_id)
    return f"{base}/api/v1/email/unsubscribe-contact?token={token}"


async def email_suppressed(db: AsyncSession, contact_id: int | None) -> bool:
    """Whether commercial email to ``contact_id`` must be suppressed.

    ``None`` is never suppressed — there is no person to have opted out.
    """
    if contact_id is None:
        return False
    result = await db.execute(select(Contact.email_opted_out_at).where(Contact.id == contact_id))
    row = result.scalar_one_or_none()
    return row is not None


async def record_email_opt_out(
    db: AsyncSession,
    contact_id: int,
    *,
    source: str = "unsubscribe_link",
) -> bool:
    """Mark a contact as opted out of commercial email.

    Idempotent: re-clicking an unsubscribe link keeps the original timestamp,
    because the date they first asked is the one that matters.
    """
    contact = await db.get(Contact, contact_id)
    if contact is None:
        return False
    if contact.email_opted_out_at is None:
        contact.email_opted_out_at = datetime.now(UTC)
        contact.email_opt_out_source = source
        logger.info("contact_email_opted_out", contact_id=contact_id, source=source)
    return True
