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

from app.core.encryption import hash_phone, hash_value
from app.models.contact import Contact
from app.utils.phone import phone_lookup_variants


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
        # ``email`` is encrypted at rest with a random IV, so look up by the
        # deterministic ``email_hash``. No workspace scope here by design: the
        # matched contact determines the workspace for the rest of the handler.
        result = await db.execute(
            select(Contact).where(Contact.email_hash == hash_value(email)).limit(1)
        )
        contact = result.scalars().first()

    if not contact and phone:
        # The encrypted ``phone_number`` column can't be matched by suffix/LIKE,
        # so match on the deterministic ``phone_hash`` across the common stored
        # formats. Skip obviously-incomplete numbers that can't identify anyone.
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 10:
            phone_hashes = [hash_phone(variant) for variant in phone_lookup_variants(phone)]
            result = await db.execute(
                select(Contact).where(Contact.phone_hash.in_(phone_hashes)).limit(1)
            )
            contact = result.scalars().first()
            if contact:
                log.info("contact_matched_by_phone_fallback", contact_id=contact.id)

    if not contact:
        log.warning("contact_not_found", email=email, phone=phone)

    return contact
