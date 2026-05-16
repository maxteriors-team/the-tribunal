"""Public demo endpoints for landing page."""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from app.api.deps import DB
from app.core.config import settings
from app.core.encryption import hash_phone, hash_value_or_none
from app.core.rate_limit_helpers import raise_rate_limited
from app.core.utils import get_client_ip
from app.models.contact import Contact
from app.models.demo_request import DemoRequest
from app.schemas.demo import (
    DemoCallRequest,
    DemoResponse,
    DemoTextRequest,
    LeadSubmitRequest,
    LeadSubmitResponse,
)
from app.services.telephony.telnyx import TelnyxSMSService
from app.services.telephony.telnyx_voice import TelnyxVoiceService
from app.utils.pii import mask_phone

router = APIRouter()
logger = structlog.get_logger()


def _seconds_until_window_clears(
    oldest_created_at: datetime | None,
    window_seconds: int,
    now: datetime,
) -> int:
    """Compute seconds until the rolling window has room for another request.

    The window is a rolling ``window_seconds`` interval. Once the oldest
    record currently in the window ages out, the caller is back under cap, so
    that's the soonest a retry can succeed. Falls back to ``window_seconds``
    if we somehow hit the cap without seeing any rows (shouldn't happen, but
    a clamped-positive default is safer than a 0 / negative header value).
    """
    if oldest_created_at is None:
        return window_seconds
    # Tolerate naive datetimes coming back from the DB driver.
    if oldest_created_at.tzinfo is None:
        oldest_created_at = oldest_created_at.replace(tzinfo=UTC)
    expires_at = oldest_created_at + timedelta(seconds=window_seconds)
    remaining = int((expires_at - now).total_seconds())
    return max(1, remaining)


async def check_rate_limits(
    db: DB,
    client_ip: str,
    phone_number: str,
    request_type: str,
) -> None:
    """Check rate limits for demo requests.

    Args:
        db: Database session
        client_ip: Client IP address
        phone_number: Phone number being requested
        request_type: Type of request (call or text)

    Raises:
        HTTPException: If rate limit exceeded
    """
    # Bypass rate limits for dev/test phone numbers
    if phone_number in settings.demo_rate_limit_bypass_phones:
        return

    now = datetime.now(UTC)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)
    hour_seconds = 3600
    day_seconds = 86400

    # Check IP rate limit: 3 requests per hour. Compute retry-after as the
    # time until the *oldest* in-window record ages out, so a client that hit
    # the cap 5 minutes ago is told to wait 55 minutes, not a flat hour.
    ip_count_result = await db.execute(
        select(func.count(), func.min(DemoRequest.created_at)).where(
            DemoRequest.client_ip == client_ip,
            DemoRequest.created_at >= hour_ago,
        )
    )
    ip_row = ip_count_result.one()
    ip_count = ip_row[0] or 0
    ip_oldest = ip_row[1]

    if ip_count >= settings.demo_ip_rate_limit:
        retry_after = _seconds_until_window_clears(ip_oldest, hour_seconds, now)
        raise_rate_limited(
            retry_after,
            detail="Rate limit exceeded. Please try again later.",
        )

    # Check phone rate limit: 2 requests per day
    phone_count_result = await db.execute(
        select(func.count(), func.min(DemoRequest.created_at)).where(
            DemoRequest.phone_number == phone_number,
            DemoRequest.created_at >= day_ago,
        )
    )
    phone_row = phone_count_result.one()
    phone_count = phone_row[0] or 0
    phone_oldest = phone_row[1]

    if phone_count >= settings.demo_phone_rate_limit:
        retry_after = _seconds_until_window_clears(phone_oldest, day_seconds, now)
        raise_rate_limited(
            retry_after,
            detail=("This phone number has reached its daily limit. Please try again tomorrow."),
        )


@router.post("/call", response_model=DemoResponse)
async def trigger_demo_call(
    demo_request: DemoCallRequest,
    request: Request,
    db: DB,
) -> DemoResponse:
    """Trigger a demo AI call to the provided phone number.

    This is a public endpoint with rate limiting.
    """
    # Validate configuration
    if not settings.demo_workspace_id or not settings.demo_agent_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo service not configured",
        )

    if not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice service not available",
        )

    client_ip = get_client_ip(request, settings.trusted_proxies)

    # Check rate limits
    await check_rate_limits(db, client_ip, demo_request.phone_number, "call")

    # Record the request
    demo_record = DemoRequest(
        phone_number=demo_request.phone_number,
        request_type="call",
        client_ip=client_ip,
    )
    db.add(demo_record)
    await db.flush()

    # Initiate the call
    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        # Build webhook URL for call events
        api_base = settings.api_base_url or "https://example.com"
        webhook_url = f"{api_base}/webhooks/telnyx/voice"

        # Connection ID is optional - service auto-discovers if not provided
        connection_id = settings.telnyx_connection_id if settings.telnyx_connection_id else None

        await voice_service.initiate_call(
            to_number=demo_request.phone_number,
            from_number=settings.demo_from_phone_number,
            connection_id=connection_id,
            webhook_url=webhook_url,
            db=db,
            workspace_id=uuid.UUID(settings.demo_workspace_id),
            contact_phone=demo_request.phone_number,
            agent_id=uuid.UUID(settings.demo_agent_id),
        )

        demo_record.status = "initiated"
        await db.commit()

        return DemoResponse(
            success=True,
            message="Call initiated! You should receive a call within 10 seconds.",
        )
    except Exception as e:
        demo_record.status = "failed"
        demo_record.error_message = str(e)[:500]
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate call. Please try again.",
        ) from e
    finally:
        await voice_service.close()


@router.post("/text", response_model=DemoResponse)
async def trigger_demo_text(
    demo_request: DemoTextRequest,
    request: Request,
    db: DB,
) -> DemoResponse:
    """Trigger a demo AI text to the provided phone number.

    This is a public endpoint with rate limiting.
    """
    # Validate configuration
    if not settings.demo_workspace_id or not settings.demo_agent_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo service not configured",
        )

    if not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS service not available",
        )

    client_ip = get_client_ip(request, settings.trusted_proxies)

    # Check rate limits
    await check_rate_limits(db, client_ip, demo_request.phone_number, "text")

    # Record the request
    demo_record = DemoRequest(
        phone_number=demo_request.phone_number,
        request_type="text",
        client_ip=client_ip,
    )
    db.add(demo_record)
    await db.flush()

    # Send initial text message
    sms_service = TelnyxSMSService(settings.telnyx_api_key)
    try:
        await sms_service.send_message(
            to_number=demo_request.phone_number,
            from_number=settings.demo_from_phone_number,
            body=(
                "Hey! This is Jess from Prestige. I help businesses automate "
                "their customer conversations with AI. Want to see what I can do? "
                "Reply with anything and let's chat!"
            ),
            db=db,
            workspace_id=uuid.UUID(settings.demo_workspace_id),
            agent_id=uuid.UUID(settings.demo_agent_id),
        )

        demo_record.status = "initiated"
        await db.commit()

        return DemoResponse(
            success=True,
            message="Text sent! Check your phone for a message from Jess.",
        )
    except Exception as e:
        demo_record.status = "failed"
        demo_record.error_message = str(e)[:500]
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send text. Please try again.",
        ) from e
    finally:
        await sms_service.close()


def _update_existing_contact(contact: Contact, lead_request: LeadSubmitRequest) -> None:
    """Update existing contact with new info from lead request."""
    contact.first_name = lead_request.first_name or contact.first_name
    contact.last_name = lead_request.last_name or contact.last_name
    contact.email = lead_request.email or contact.email
    contact.company_name = lead_request.company_name or contact.company_name
    if lead_request.notes:
        existing_notes = contact.notes or ""
        contact.notes = f"{existing_notes}\n---\n{lead_request.notes}".strip()


async def _trigger_demo_call(lead_request: LeadSubmitRequest, db: DB) -> bool:
    """Trigger a demo call. Returns True if successful."""
    try:
        voice_service = TelnyxVoiceService(settings.telnyx_api_key)
        api_base = settings.api_base_url or "https://example.com"
        await voice_service.initiate_call(
            to_number=lead_request.phone_number,
            from_number=settings.demo_from_phone_number,
            connection_id=settings.telnyx_connection_id or None,
            webhook_url=f"{api_base}/webhooks/telnyx/voice",
            db=db,
            workspace_id=uuid.UUID(settings.demo_workspace_id),
            contact_phone=lead_request.phone_number,
            agent_id=uuid.UUID(settings.demo_agent_id),
        )
        await voice_service.close()
        return True
    except Exception:
        logger.exception("demo_call_trigger_failed", phone=mask_phone(lead_request.phone_number))
        return False


async def _trigger_demo_text(lead_request: LeadSubmitRequest, db: DB) -> bool:
    """Trigger a demo text. Returns True if successful."""
    try:
        sms_service = TelnyxSMSService(settings.telnyx_api_key)
        await sms_service.send_message(
            to_number=lead_request.phone_number,
            from_number=settings.demo_from_phone_number,
            body=(
                f"Hey {lead_request.first_name}! This is Jess from Prestige. "
                "Thanks for your interest! I help businesses automate their "
                "customer conversations with AI. Reply with anything and let's chat!"
            ),
            db=db,
            workspace_id=uuid.UUID(settings.demo_workspace_id),
            agent_id=uuid.UUID(settings.demo_agent_id),
        )
        await sms_service.close()
        return True
    except Exception:
        logger.exception("demo_text_trigger_failed", phone=mask_phone(lead_request.phone_number))
        return False


@router.post("/leads", response_model=LeadSubmitResponse)
async def submit_lead(
    lead_request: LeadSubmitRequest,
    request: Request,
    db: DB,
) -> LeadSubmitResponse:
    """Submit a lead from the landing page.

    Creates a contact in the demo workspace. Optionally triggers a demo call or text.
    This is a public endpoint with rate limiting.
    """
    if not settings.demo_workspace_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lead submission not configured",
        )

    client_ip = get_client_ip(request, settings.trusted_proxies)
    await check_rate_limits(db, client_ip, lead_request.phone_number, "lead")

    # Check if contact already exists in demo workspace — lookup via the
    # deterministic phone hash, not the Fernet-encrypted plaintext column.
    workspace_id = uuid.UUID(settings.demo_workspace_id)
    result = await db.execute(
        select(Contact).where(
            Contact.workspace_id == workspace_id,
            Contact.phone_hash == hash_phone(lead_request.phone_number),
        )
    )
    existing_contact = result.scalar_one_or_none()

    if existing_contact:
        _update_existing_contact(existing_contact, lead_request)
        contact = existing_contact
    else:
        contact = Contact(
            workspace_id=workspace_id,
            first_name=lead_request.first_name,
            last_name=lead_request.last_name,
            phone_number=lead_request.phone_number,
            phone_hash=hash_phone(lead_request.phone_number),
            email=lead_request.email,
            email_hash=hash_value_or_none(lead_request.email),
            company_name=lead_request.company_name,
            notes=lead_request.notes,
            source=lead_request.source or "landing_page",
            status="new",
        )
        db.add(contact)

    demo_record = DemoRequest(
        phone_number=lead_request.phone_number,
        request_type="lead",
        client_ip=client_ip,
    )
    db.add(demo_record)
    await db.flush()

    # Optionally trigger demo call or text
    demo_initiated = False
    can_trigger = settings.demo_agent_id and settings.telnyx_api_key
    if can_trigger and lead_request.trigger_call:
        demo_initiated = await _trigger_demo_call(lead_request, db)
    elif can_trigger and lead_request.trigger_text:
        demo_initiated = await _trigger_demo_text(lead_request, db)

    demo_record.status = "initiated"
    await db.commit()

    message = "Thanks for your interest! We'll be in touch soon."
    if demo_initiated and lead_request.trigger_call:
        message = "Thanks! You should receive a call within 10 seconds."
    elif demo_initiated:
        message = "Thanks! Check your phone for a text from Jess."

    return LeadSubmitResponse(
        success=True,
        message=message,
        contact_id=contact.id,
        demo_initiated=demo_initiated,
    )
