"""Text a client-facing link (proposal, estimate, invoice) over SMS.

One home for the delivery rails every customer-facing text has to honour:
Telnyx is configured, the number hasn't opted out, and the workspace owns an
SMS-capable sender. Extracted from ``QuoteService`` so invoices reuse the exact
same checks rather than growing a second, subtly different copy -- an opt-out
respected on proposals but missed on invoices would be a compliance problem, not
a style inconsistency.

Every refusal names the fix. A rep watching a button fail can act on "add a
number under Settings" and cannot act on a generic send error.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.exceptions import ValidationError


async def any_sms_number(db: AsyncSession, workspace_id: uuid.UUID) -> str | None:
    """Oldest active SMS-enabled workspace number (agentless fallback)."""
    from app.models.phone_number import PhoneNumber

    result = await db.execute(
        select(PhoneNumber.phone_number)
        .where(
            and_(
                PhoneNumber.workspace_id == workspace_id,
                PhoneNumber.is_active.is_(True),
                PhoneNumber.sms_enabled.is_(True),
            )
        )
        .order_by(PhoneNumber.created_at)
        .limit(1)
    )
    phone = result.scalar_one_or_none()
    return str(phone) if phone else None


async def send_client_link_sms(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    phone: str,
    contact_id: int | None,
    body: str,
    idempotency_scope: str,
    idempotency_id: uuid.UUID,
) -> None:
    """Text a client-facing link, or raise ``ValidationError`` saying why not.

    The sender follows the contact's own conversation when there is one, so a
    homeowner sees the number that has been texting them all along rather than a
    stranger's.
    """
    from app.core.config import settings
    from app.services.calendar.reminder_service import resolve_from_number
    from app.services.idempotency import derive_outbound_key
    from app.services.rate_limiting.opt_out_manager import OptOutManager
    from app.services.telephony.telnyx import TelnyxSMSService

    if not settings.telnyx_api_key:
        raise ValidationError("Texting isn't configured (Telnyx API key missing).")

    if await OptOutManager().check_opt_out(workspace_id, phone, db):
        raise ValidationError("This phone number has opted out of texts.")

    from_number = None
    if contact_id is not None:
        from_number = await resolve_from_number(db, contact_id, workspace_id, None)
    if not from_number:
        from_number = await any_sms_number(db, workspace_id)
    if not from_number:
        raise ValidationError(
            "No SMS-enabled phone number in this workspace — add one under Settings."
        )

    sms = TelnyxSMSService(settings.telnyx_api_key)
    try:
        await sms.send_message(
            to_number=phone,
            from_number=from_number,
            body=body,
            db=db,
            workspace_id=workspace_id,
            idempotency_key=derive_outbound_key(
                idempotency_scope,
                idempotency_id,
                phone,
                datetime.now(UTC).isoformat(),
            ),
        )
    finally:
        await sms.close()
