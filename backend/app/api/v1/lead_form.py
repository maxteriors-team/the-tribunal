"""Public lead form endpoint for external website submissions."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB
from app.core.config import settings
from app.core.encryption import hash_phone, hash_value, hash_value_or_none
from app.core.origin_validation import validate_origin
from app.core.rate_limit_helpers import raise_rate_limited
from app.core.utils import get_client_ip
from app.db.scope import apply_workspace_scope
from app.models.campaign import CampaignContact
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.demo_request import DemoRequest
from app.models.lead_source import LeadSource, LeadSourceCampaign
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.lead_source import LeadSubmitRequest, LeadSubmitResponse
from app.schemas.speed_to_lead import SpeedToLeadProofResponse
from app.services.contacts.address_parsing import parse_us_address
from app.services.idempotency import derive_outbound_key
from app.services.lead_sources.attribution_service import (
    WebAttributionInput,
    apply_web_attribution,
)
from app.services.notifications import notify_workspace_event
from app.services.sla.speed_to_lead import (
    MIN_LEADS_FOR_PUBLIC_BADGE,
    compute_sla_metrics,
    get_speed_to_lead_settings,
)
from app.services.telephony.telnyx import TelnyxSMSService
from app.services.telephony.telnyx_voice import TelnyxVoiceService

logger = structlog.get_logger()

router = APIRouter()


async def _check_lead_form_rate_limit(db: DB, client_ip: str) -> None:
    """Check IP rate limit for lead form submissions.

    On 429 the response includes a ``Retry-After`` header (seconds) computed
    from when the oldest in-window submission will age out — so clients back
    off only as long as the rolling window actually requires.
    """
    now = datetime.now(UTC)
    window_seconds = 3600
    hour_ago = now - timedelta(seconds=window_seconds)
    result = await db.execute(
        select(func.count(), func.min(DemoRequest.created_at)).where(
            DemoRequest.client_ip == client_ip,
            DemoRequest.request_type == "lead_form",
            DemoRequest.created_at >= hour_ago,
        )
    )
    row = result.one()
    count = row[0] or 0
    oldest = row[1]
    if count >= settings.lead_form_ip_rate_limit:
        retry_after = window_seconds
        if oldest is not None:
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=UTC)
            retry_after = max(
                1, int((oldest + timedelta(seconds=window_seconds) - now).total_seconds())
            )
        raise_rate_limited(
            retry_after,
            detail="Rate limit exceeded. Please try again later.",
        )


async def _action_auto_text(lead_source: LeadSource, contact: Contact, db: DB) -> None:
    """Send an automatic text message to the lead."""
    config = lead_source.action_config or {}
    from_number = config.get("from_phone_number", settings.demo_from_phone_number)
    template = config.get("message_template") or (
        f"Hi {contact.first_name}! Thanks for your interest. We'll be in touch shortly."
    )
    # Substitute {first_name} placeholder in custom templates
    template = template.replace("{first_name}", contact.first_name or "")
    if not settings.telnyx_api_key or not from_number:
        logger.warning("auto_text_skipped", reason="telnyx not configured")
        return
    sms_service = TelnyxSMSService(settings.telnyx_api_key)
    agent_id_str = config.get("agent_id")
    agent_id = uuid.UUID(agent_id_str) if agent_id_str else None
    try:
        idempotency_key = derive_outbound_key("lead_form_auto_text", lead_source.id, contact.id)
        await sms_service.send_message(
            to_number=contact.phone_number,
            from_number=from_number,
            body=template,
            db=db,
            workspace_id=lead_source.workspace_id,
            agent_id=agent_id,
            idempotency_key=idempotency_key,
        )
        # Assign agent to the conversation so replies get AI responses
        if agent_id:
            from app.utils.phone import normalize_phone_safe

            norm_from = normalize_phone_safe(from_number) or from_number
            norm_to = normalize_phone_safe(contact.phone_number) or contact.phone_number
            conv_result = await db.execute(
                apply_workspace_scope(
                    select(Conversation),
                    Conversation,
                    lead_source.workspace_id,
                ).where(
                    Conversation.workspace_phone == norm_from,
                    Conversation.contact_phone == norm_to,
                )
            )
            conversation = conv_result.scalar_one_or_none()
            if conversation:
                conversation.assigned_agent_id = agent_id
                conversation.ai_enabled = True
    except Exception:
        logger.exception("auto_text_failed", contact_id=contact.id)
    finally:
        await sms_service.close()


async def _action_auto_call(lead_source: LeadSource, contact: Contact, db: DB) -> None:
    """Initiate an automatic call to the lead."""
    config = lead_source.action_config or {}
    from_number = config.get("from_phone_number", settings.demo_from_phone_number)
    if not settings.telnyx_api_key or not from_number:
        logger.warning("auto_call_skipped", reason="telnyx not configured")
        return
    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        api_base = settings.api_base_url or "https://example.com"
        agent_id_str = config.get("agent_id")
        idempotency_key = derive_outbound_key("lead_form_auto_call", lead_source.id, contact.id)
        await voice_service.initiate_call(
            to_number=contact.phone_number,
            from_number=from_number,
            connection_id=settings.telnyx_connection_id or None,
            webhook_url=f"{api_base}/webhooks/telnyx/voice",
            db=db,
            workspace_id=lead_source.workspace_id,
            contact_phone=contact.phone_number,
            agent_id=uuid.UUID(agent_id_str) if agent_id_str else None,
            idempotency_key=idempotency_key,
        )
    except Exception:
        logger.exception("auto_call_failed", contact_id=contact.id)
    finally:
        await voice_service.close()


async def _action_enroll_campaign(lead_source: LeadSource, contact: Contact, db: DB) -> None:
    """Enroll the lead in a campaign."""
    config = lead_source.action_config or {}
    campaign_id_str = config.get("campaign_id")
    if not campaign_id_str:
        logger.warning("enroll_campaign_skipped", reason="no campaign_id")
        return
    try:
        campaign_id = uuid.UUID(campaign_id_str)
        existing = await db.execute(
            select(CampaignContact).where(
                CampaignContact.campaign_id == campaign_id,
                CampaignContact.contact_id == contact.id,
            )
        )
        if not existing.scalar_one_or_none():
            cc = CampaignContact(
                campaign_id=campaign_id,
                contact_id=contact.id,
                status="pending",
            )
            db.add(cc)
    except Exception:
        logger.exception("enroll_campaign_failed", contact_id=contact.id)


_ACTION_HANDLERS = {
    "auto_text": _action_auto_text,
    "auto_call": _action_auto_call,
    "enroll_campaign": _action_enroll_campaign,
}


async def _execute_action(
    lead_source: LeadSource,
    contact: Contact,
    db: DB,
) -> None:
    """Execute the post-capture action configured on the lead source."""
    handler = _ACTION_HANDLERS.get(lead_source.action)
    if handler:
        await handler(lead_source, contact, db)


async def _notify_new_lead(lead_source: LeadSource, contact: Contact, db: DB) -> None:
    """Notify workspace members about a new lead via push, email, and SMS."""
    config = lead_source.action_config or {}
    from_number = config.get("from_phone_number", settings.demo_from_phone_number)
    name = contact.first_name or "Unknown"
    if contact.last_name:
        name = f"{name} {contact.last_name}"

    body = f"New lead: {name} - {contact.phone_number}"
    source_label = lead_source.name or "Website form"

    # Push + email fan-out to every workspace member, gated per user by the
    # master push/email toggles and the ``new_lead`` per-type preference.
    try:
        await notify_workspace_event(
            db,
            workspace_id=lead_source.workspace_id,
            notification_type="new_lead",
            title="New Lead",
            body=body,
            data={
                "type": "new_lead",
                "contactId": str(contact.id),
            },
            email_subject=f"New lead: {name}",
            email_heading="New lead captured",
            email_intro=f"{name} just submitted your {source_label} form.",
            email_details={
                "Name": name,
                "Phone": contact.phone_number or "\u2014",
                "Email": contact.email or "\u2014",
                "Source": source_label,
            },
            dedupe_key=f"new_lead:{contact.id}",
        )
    except Exception:
        logger.exception("lead_event_notification_failed", contact_id=contact.id)

    # Send SMS notification to workspace members who have SMS notifications enabled
    if not settings.telnyx_api_key or not from_number:
        return

    result = await db.execute(
        apply_workspace_scope(
            select(WorkspaceMembership).options(selectinload(WorkspaceMembership.user)),
            WorkspaceMembership,
            lead_source.workspace_id,
        )
    )
    members = result.scalars().all()

    async with httpx.AsyncClient(timeout=15.0) as client:
        for member in members:
            user = member.user
            if not user.notification_sms or not user.phone_number:
                continue
            try:
                await client.post(
                    "https://api.telnyx.com/v2/messages",
                    headers={
                        "Authorization": f"Bearer {settings.telnyx_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": from_number,
                        "to": user.phone_number,
                        "text": body,
                        "type": "SMS",
                    },
                )
            except Exception:
                logger.exception(
                    "lead_sms_notification_failed",
                    user_id=user.id,
                    contact_id=contact.id,
                )


@router.options("/{public_key}")
async def lead_form_preflight(
    public_key: str,
    request: Request,
    db: DB,
) -> Response:
    """Handle CORS preflight for lead form submissions."""
    result = await db.execute(
        select(LeadSource).where(
            LeadSource.public_key == public_key,
            LeadSource.enabled.is_(True),
        )
    )
    lead_source = result.scalar_one_or_none()

    origin = request.headers.get("origin", "")
    if lead_source and validate_origin(request, lead_source.allowed_domains):
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "86400",
            },
        )
    return Response(status_code=403)


def _empty_proof(sla_seconds: int, window_days: int) -> SpeedToLeadProofResponse:
    """Return a disabled proof badge (off, or sample too small to publish)."""
    return SpeedToLeadProofResponse(
        enabled=False,
        sla_seconds=sla_seconds,
        window_days=window_days,
        leads_measured=0,
        pct_within_sla=None,
        median_response_seconds=None,
        headline=None,
    )


@router.options("/{public_key}/proof")
async def lead_form_proof_preflight(
    public_key: str,
    request: Request,
    db: DB,
) -> Response:
    """Handle CORS preflight for the public speed-to-lead proof badge."""
    result = await db.execute(
        select(LeadSource).where(
            LeadSource.public_key == public_key,
            LeadSource.enabled.is_(True),
        )
    )
    lead_source = result.scalar_one_or_none()
    origin = request.headers.get("origin", "")
    if lead_source and validate_origin(request, lead_source.allowed_domains):
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "86400",
            },
        )
    return Response(status_code=403)


@router.get("/{public_key}/proof", response_model=SpeedToLeadProofResponse)
async def get_lead_form_proof(
    public_key: str,
    request: Request,
    response: Response,
    db: DB,
) -> SpeedToLeadProofResponse:
    """Public speed-to-lead proof badge for embedding on a lead-form widget.

    Origin-validated against the lead source's allowed domains. Returns a
    disabled badge (no stats) unless the workspace opted in and has enough
    measured leads to publish an honest headline.
    """
    result = await db.execute(select(LeadSource).where(LeadSource.public_key == public_key))
    lead_source = result.scalar_one_or_none()
    if not lead_source or not lead_source.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found")
    if not validate_origin(request, lead_source.allowed_domains):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")

    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin

    workspace = await db.get(Workspace, lead_source.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    config = get_speed_to_lead_settings(workspace)
    if not (config.enabled and config.badge_enabled):
        return _empty_proof(config.sla_seconds, config.badge_window_days)

    metrics = await compute_sla_metrics(
        db,
        workspace.id,
        sla_seconds=config.sla_seconds,
        window_days=config.badge_window_days,
    )
    if metrics.leads_measured < MIN_LEADS_FOR_PUBLIC_BADGE or metrics.pct_within_sla is None:
        return _empty_proof(config.sla_seconds, config.badge_window_days)

    headline = f"{metrics.pct_within_sla}% of leads answered in under {config.sla_seconds}s"
    return SpeedToLeadProofResponse(
        enabled=True,
        sla_seconds=config.sla_seconds,
        window_days=config.badge_window_days,
        leads_measured=metrics.leads_measured,
        pct_within_sla=metrics.pct_within_sla,
        median_response_seconds=metrics.median_response_seconds,
        headline=headline,
    )


def _upsert_contact_from_lead(
    db: DB,
    lead_source: LeadSource,
    body: LeadSubmitRequest,
    existing_contact: Contact | None,
) -> Contact:
    """Fold a public submission into the deduped contact, or create one."""
    if existing_contact:
        # Update existing contact with new info. Keep email/email_hash in sync.
        existing_contact.first_name = body.first_name or existing_contact.first_name
        existing_contact.last_name = body.last_name or existing_contact.last_name
        if body.email:
            existing_contact.email = body.email
            existing_contact.email_hash = hash_value(body.email)
        existing_contact.company_name = body.company_name or existing_contact.company_name
        _apply_address(existing_contact, body.address)
        if body.notes:
            existing_notes = existing_contact.notes or ""
            existing_contact.notes = f"{existing_notes}\n---\n{body.notes}".strip()
        if body.source_detail:
            existing_notes = existing_contact.notes or ""
            existing_contact.notes = f"{existing_notes}\n[source: {body.source_detail}]".strip()
        return existing_contact

    notes = body.notes or ""
    if body.source_detail:
        source_tag = f"[source: {body.source_detail}]"
        notes = f"{notes}\n{source_tag}".strip() if notes else source_tag
    contact = Contact(
        workspace_id=lead_source.workspace_id,
        first_name=body.first_name,
        last_name=body.last_name,
        phone_number=body.phone_number,
        phone_hash=hash_phone(body.phone_number),
        email=body.email,
        email_hash=hash_value_or_none(body.email),
        company_name=body.company_name,
        notes=notes or None,
        source="lead_form",
        status="new",
    )
    _apply_address(contact, body.address)
    db.add(contact)
    return contact


def _apply_address(contact: Contact, raw_address: str | None) -> None:
    """Fill the contact's structured address columns from a free-form string.

    A newer submission overwrites the stored address (a returning lead often
    re-quotes with a corrected or different property), but a submission with
    no address never erases one we already have. Parsed parts that are
    missing (e.g. hand-typed street only) leave their columns untouched
    rather than blanking a previously complete address.
    """
    if not raw_address:
        return
    parsed = parse_us_address(raw_address)
    if parsed is None:
        return
    contact.address_line1 = parsed.line1
    if parsed.city:
        contact.address_city = parsed.city
    if parsed.state:
        contact.address_state = parsed.state
    if parsed.zip_code:
        contact.address_zip = parsed.zip_code


async def _resolve_owned_campaign_id(
    db: DB, lead_source: LeadSource, campaign_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Return the campaign id only if it belongs to this lead source, else None."""
    if campaign_id is None:
        return None
    result = await db.execute(
        select(LeadSourceCampaign.id).where(
            LeadSourceCampaign.id == campaign_id,
            LeadSourceCampaign.lead_source_id == lead_source.id,
            LeadSourceCampaign.workspace_id == lead_source.workspace_id,
        )
    )
    return campaign_id if result.scalar_one_or_none() is not None else None


@router.post("/{public_key}", response_model=LeadSubmitResponse)
async def submit_lead(
    public_key: str,
    body: LeadSubmitRequest,
    request: Request,
    db: DB,
) -> Response:
    """Submit a lead from an external website form.

    Public endpoint secured by origin whitelist and rate limiting.
    """
    # Look up lead source
    result = await db.execute(select(LeadSource).where(LeadSource.public_key == public_key))
    lead_source = result.scalar_one_or_none()

    if not lead_source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found")

    if not lead_source.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Lead source is disabled")

    # Validate origin
    if not validate_origin(request, lead_source.allowed_domains):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")

    # A public submitter could pass any campaign UUID; only honor one that
    # actually belongs to this lead source so attribution can't be poisoned
    # with a cross-workspace campaign id.
    attributed_campaign_id = await _resolve_owned_campaign_id(
        db, lead_source, body.lead_source_campaign_id
    )

    # Rate limit
    client_ip = get_client_ip(request, settings.trusted_proxies)
    await _check_lead_form_rate_limit(db, client_ip)

    # Record rate limit entry
    demo_record = DemoRequest(
        phone_number=body.phone_number,
        request_type="lead_form",
        client_ip=client_ip,
    )
    db.add(demo_record)

    # Deduplicate: find existing contact by phone in workspace — via hash.
    existing_result = await db.execute(
        apply_workspace_scope(select(Contact), Contact, lead_source.workspace_id).where(
            Contact.phone_hash == hash_phone(body.phone_number)
        )
    )
    existing_contact = existing_result.scalar_one_or_none()

    is_new_lead = existing_contact is None
    contact = _upsert_contact_from_lead(db, lead_source, body, existing_contact)

    # Record SMS consent ONLY when the website form's optional checkbox was
    # explicitly ticked (10DLC/TCR: consent must never be bundled into form
    # submission). An unchecked box never downgrades existing consent.
    if body.sms_consent:
        contact.sms_consent_status = "opted_in"
        contact.sms_consent_source = f"lead_form:{lead_source.name or public_key}"
        contact.sms_consent_collected_at = datetime.now(UTC)
        page = f" on {body.landing_page}" if body.landing_page else ""
        contact.sms_consent_notes = f"Checked optional SMS-consent checkbox{page}"

    # Persist first/latest-touch attribution + tracking signals so web leads
    # feed the lead-source ROI ranking instead of landing in the unknown queue.
    # Confidence is intentionally NOT taken from the request: this is a public
    # endpoint, so a caller-supplied value would let anyone inflate the ROI
    # confidence rollup. A known lead-source form gets the server default.
    apply_web_attribution(
        contact,
        lead_source,
        WebAttributionInput(
            lead_source_campaign_id=attributed_campaign_id,
            utm_source=body.utm_source,
            utm_medium=body.utm_medium,
            utm_campaign=body.utm_campaign,
            utm_content=body.utm_content,
            utm_term=body.utm_term,
            gclid=body.gclid,
            fbclid=body.fbclid,
            landing_page=body.landing_page,
            referrer=body.referrer,
        ),
    )

    await db.flush()

    # Execute post-capture action
    await _execute_action(lead_source, contact, db)

    # Notify workspace members about new lead via SMS and push
    if is_new_lead:
        try:
            await _notify_new_lead(lead_source, contact, db)
        except Exception:
            logger.exception("lead_notification_failed", contact_id=contact.id)

    demo_record.status = "initiated"
    await db.commit()

    # Build response with CORS header
    origin = request.headers.get("origin", "")
    response_data = LeadSubmitResponse(
        success=True,
        message="Thank you! Your information has been received.",
    )

    return Response(
        content=response_data.model_dump_json(),
        media_type="application/json",
        headers={"Access-Control-Allow-Origin": origin},
    )
