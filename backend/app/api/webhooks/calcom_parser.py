"""Cal.com webhook payload parsing helpers.

Pure-ish parsing / lookup utilities used by the Cal.com webhook handlers:
- Attendee -> Contact resolution (email, phone-fallback)

Signature verification for Cal.com webhooks lives in
``app.core.webhook_security``; this module intentionally stays a thin parser
layer so handlers/events can be tested independently.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from app.models.contact import Contact


async def find_contact_by_attendee(
    email: str | None,
    phone: str | None,
    db: Any,
    log: Any,
) -> Contact | None:
    """Look up a :class:`Contact` by email, falling back to phone number.

    Args:
        email: Attendee email address (may be empty/None).
        phone: Attendee phone number in any format (may be empty/None).
        db: Async SQLAlchemy session.
        log: Bound structlog logger.

    Returns:
        Matched Contact ORM object, or ``None`` when no match is found.
    """
    contact: Contact | None = None

    if email:
        result = await db.execute(select(Contact).where(Contact.email == email))
        contact = result.scalar_one_or_none()

    if not contact and phone:
        # Normalise: keep digits only, then match the last 10 digits
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 10:
            suffix = digits[-10:]
            result = await db.execute(
                select(Contact).where(Contact.phone_number.like(f"%{suffix}"))
            )
            contact = result.scalar_one_or_none()
            if contact:
                log.info("contact_matched_by_phone_fallback", contact_id=contact.id)

    if not contact:
        log.warning("contact_not_found", email=email, phone=phone)

    return contact
