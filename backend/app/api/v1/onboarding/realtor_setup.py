"""Realtor self-serve onboarding flow.

Workspace setup, Cal.com wiring, agent provisioning, phone-number purchase,
CSV upload + drip-campaign enrollment, and the realtor dashboard stats
endpoint. Extracted from the original ``app/api/v1/realtor.py`` god file.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, get_workspace
from app.api.v1.integrations.followupboss import upsert_fub_integration
from app.core.config import settings
from app.core.encryption import decrypt_json, encrypt_json
from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.campaign import Campaign, CampaignContact, CampaignStatus
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.phone_number import PhoneNumber
from app.models.workspace import Workspace, WorkspaceIntegration, WorkspaceMembership
from app.schemas.realtor import (
    ParseCalcomUrlRequest,
    ParseCalcomUrlResponse,
    RealtorCampaignResponse,
    RealtorOnboardRequest,
    RealtorOnboardResponse,
    VerifyCalcomResponse,
)
from app.services.agents.realtor_template import (
    get_realtor_agent_config,
    get_realtor_campaign_defaults,
)
from app.services.contacts import ContactImportService
from app.services.reactivation.drip_bootstrap import auto_create_drip_for_imports
from app.services.telephony.telnyx import TelnyxSMSService

router = APIRouter()
workspace_router = APIRouter()
logger = structlog.get_logger()

_CALCOM_URL_RE = re.compile(r"^https?://(?:app\.)?cal\.com/([^/?#]+)/([^/?#]+)")
_CALCOM_V1_BASE = "https://api.cal.com/v1"
_CALCOM_V2_BASE = "https://api.cal.com/v2"


class RealtorStatsResponse(BaseModel):
    """Realtor dashboard stats."""

    leads_uploaded: int
    texts_sent: int
    replies_received: int
    appointments_booked: int


async def _get_user_workspace(current_user: CurrentUser, db: DB) -> Workspace:
    """Resolve the user's default (or first) workspace."""
    result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.is_default.is_(True),
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        result = await db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == current_user.id)
            .order_by(WorkspaceMembership.created_at.asc())
            .limit(1)
        )
        membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No workspace found. Please create a workspace first.",
        )

    ws_result = await db.execute(
        select(Workspace).where(
            Workspace.id == membership.workspace_id,
            Workspace.is_active.is_(True),
        )
    )
    workspace = ws_result.scalar_one_or_none()

    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace not found or is inactive.",
        )

    return workspace


async def _get_workspace_calcom_api_key(
    workspace_id: uuid.UUID,
    db: DB,
) -> str | None:
    """Return the stored Cal.com API key for the workspace, or None if not set."""
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace_id,
            WorkspaceIntegration.integration_type == "calcom",
            WorkspaceIntegration.is_active.is_(True),
        )
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        return None
    try:
        creds = decrypt_json(integration.encrypted_credentials)
        return creds.get("api_key") or None
    except Exception:
        return None


@workspace_router.get("/stats", response_model=RealtorStatsResponse)
async def get_realtor_stats(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> RealtorStatsResponse:
    """Get realtor dashboard statistics for a workspace.

    Returns:
    - leads_uploaded: total contacts in the workspace
    - texts_sent: outbound messages
    - replies_received: inbound messages
    - appointments_booked: confirmed or completed appointments
    """
    leads_result = await db.execute(
        select(func.count()).select_from(Contact).where(
            Contact.workspace_id == workspace_id
        )
    )
    leads_uploaded = leads_result.scalar() or 0

    workspace_conversations = select(Conversation.id).where(
        Conversation.workspace_id == workspace_id
    )

    texts_sent_result = await db.execute(
        select(func.count()).select_from(Message).where(
            Message.conversation_id.in_(workspace_conversations),
            Message.direction == MessageDirection.OUTBOUND,
        )
    )
    texts_sent = texts_sent_result.scalar() or 0

    replies_result = await db.execute(
        select(func.count()).select_from(Message).where(
            Message.conversation_id.in_(workspace_conversations),
            Message.direction == MessageDirection.INBOUND,
        )
    )
    replies_received = replies_result.scalar() or 0

    appointments_result = await db.execute(
        select(func.count()).select_from(Appointment).where(
            Appointment.workspace_id == workspace_id,
            Appointment.status.in_([
                AppointmentStatus.SCHEDULED,
                AppointmentStatus.COMPLETED,
            ]),
        )
    )
    appointments_booked = appointments_result.scalar() or 0

    return RealtorStatsResponse(
        leads_uploaded=leads_uploaded,
        texts_sent=texts_sent,
        replies_received=replies_received,
        appointments_booked=appointments_booked,
    )


@router.post(
    "/onboard",
    response_model=RealtorOnboardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def realtor_onboard(
    request: RealtorOnboardRequest,
    current_user: CurrentUser,
    db: DB,
) -> RealtorOnboardResponse:
    """Complete realtor onboarding in a single call.

    Creates an AI agent from the realtor template, stores the Cal.com
    integration, and attempts to auto-purchase a phone number. The phone
    number step is best-effort — onboarding succeeds even if it fails.
    """
    workspace = await _get_user_workspace(current_user, db)
    workspace_id = workspace.id

    # 1. Create the AI agent from the realtor template
    agent_config = get_realtor_agent_config()
    agent = Agent(
        workspace_id=workspace_id,
        name="Realtor Lead Reactivation Agent",
        calcom_event_type_id=request.calcom_event_type_id,
        **agent_config,
    )
    db.add(agent)
    await db.flush()

    logger.info(
        "realtor_agent_created",
        workspace_id=str(workspace_id),
        agent_id=str(agent.id),
        user_id=current_user.id,
    )

    # 2. Store the Cal.com integration (upsert).
    calcom_result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace_id,
            WorkspaceIntegration.integration_type == "calcom",
        )
    )
    existing_integration = calcom_result.scalar_one_or_none()

    if existing_integration is not None:
        existing_integration.encrypted_credentials = encrypt_json(
            {"api_key": request.calcom_api_key}
        )
        existing_integration.is_active = True
    else:
        integration = WorkspaceIntegration(
            workspace_id=workspace_id,
            integration_type="calcom",
            encrypted_credentials=encrypt_json({"api_key": request.calcom_api_key}),
            is_active=True,
        )
        db.add(integration)

    logger.info(
        "calcom_integration_stored",
        workspace_id=str(workspace_id),
        user_id=current_user.id,
    )

    # 2b. Store the Follow Up Boss integration (optional)
    if request.fub_api_key:
        await upsert_fub_integration(db, workspace_id, request.fub_api_key)
        logger.info(
            "fub_integration_stored",
            workspace_id=str(workspace_id),
            user_id=current_user.id,
        )

    # 3. Auto-purchase a phone number (best-effort).
    phone_number_id: uuid.UUID | None = None
    phone_number_str: str | None = None

    if settings.telnyx_api_key:
        telnyx = TelnyxSMSService(settings.telnyx_api_key)
        try:
            available = await telnyx.search_phone_numbers(
                country="US",
                area_code=request.area_code,
                limit=5,
            )

            if available:
                purchased = await telnyx.purchase_phone_number(available[0].phone_number)
                phone_record = PhoneNumber(
                    workspace_id=workspace_id,
                    phone_number=purchased.phone_number,
                    telnyx_phone_number_id=purchased.id,
                    sms_enabled=True,
                    voice_enabled=True,
                    is_active=True,
                )
                db.add(phone_record)
                await db.flush()

                phone_number_id = phone_record.id
                phone_number_str = purchased.phone_number

                logger.info(
                    "phone_number_provisioned",
                    workspace_id=str(workspace_id),
                    phone_number=phone_number_str,
                )
            else:
                logger.warning(
                    "no_available_phone_numbers",
                    workspace_id=str(workspace_id),
                    area_code=request.area_code,
                )
        except Exception as exc:
            logger.error(
                "phone_number_provisioning_failed",
                workspace_id=str(workspace_id),
                error=str(exc),
            )
        finally:
            await telnyx.close()
    else:
        logger.warning(
            "telnyx_not_configured_skipping_phone_purchase",
            workspace_id=str(workspace_id),
        )

    # 4. Commit everything
    await db.commit()

    if phone_number_str:
        message = f"Onboarding complete. Phone number {phone_number_str} provisioned."
    else:
        message = (
            "Onboarding complete. No phone number was provisioned — "
            "you can add one from Settings → Phone Numbers."
        )

    return RealtorOnboardResponse(
        workspace_id=workspace_id,
        agent_id=agent.id,
        phone_number_id=phone_number_id,
        phone_number=phone_number_str,
        calcom_connected=True,
        message=message,
    )


@router.post(
    "/campaigns",
    response_model=RealtorCampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_realtor_campaign(
    current_user: CurrentUser,
    db: DB,
    file: UploadFile,
    skip_duplicates: bool = Form(default=True),
    campaign_name: str | None = Form(default=None),
) -> RealtorCampaignResponse:
    """Upload a CSV and launch a realtor lead-reactivation campaign in one call.

    Steps performed atomically:
    1. Read the uploaded CSV file.
    2. Import contacts using the standard ContactImportService.
    3. Find the workspace's realtor agent (by name or channel_mode="text").
    4. Find the workspace's first active phone number.
    5. Create a Campaign with realtor defaults.
    6. Enroll all imported contacts in the campaign.
    7. Start the campaign (status → running).
    """
    workspace = await _get_user_workspace(current_user, db)
    workspace_id = workspace.id

    # 1. Read CSV
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV file.",
        )

    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {exc!s}",
        ) from exc

    # 2. Import contacts
    import_service = ContactImportService(db)
    try:
        import_result = await import_service.import_csv(
            workspace_id=workspace_id,
            file_content=content,
            skip_duplicates=skip_duplicates,
            source="realtor_csv_upload",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not import_result.created_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No contacts were imported from the CSV. "
                f"Rows processed: {import_result.total_rows}, "
                f"failed: {import_result.failed}, "
                f"skipped: {import_result.skipped_duplicates}."
            ),
        )

    # 3. Find the realtor agent
    agent_result = await db.execute(
        select(Agent)
        .where(
            Agent.workspace_id == workspace_id,
            Agent.name == "Realtor Lead Reactivation Agent",
        )
        .limit(1)
    )
    agent = agent_result.scalar_one_or_none()

    if agent is None:
        fallback_result = await db.execute(
            select(Agent)
            .where(
                Agent.workspace_id == workspace_id,
                Agent.channel_mode == "text",
            )
            .order_by(Agent.created_at.asc())
            .limit(1)
        )
        agent = fallback_result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No realtor agent found in this workspace. "
                "Complete onboarding first to create the agent."
            ),
        )

    # 4. Find the workspace's active phone number
    phone_result = await db.execute(
        select(PhoneNumber)
        .where(
            PhoneNumber.workspace_id == workspace_id,
            PhoneNumber.is_active.is_(True),
            PhoneNumber.sms_enabled.is_(True),
        )
        .order_by(PhoneNumber.created_at.asc())
        .limit(1)
    )
    phone_record = phone_result.scalar_one_or_none()

    if phone_record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No active SMS-enabled phone number found in this workspace. "
                "Complete onboarding first or add a phone number from Settings."
            ),
        )

    # 5. Create the campaign
    defaults = get_realtor_campaign_defaults()
    date_str = datetime.now(UTC).strftime("%B %d, %Y")
    resolved_name = campaign_name or f"Lead Reactivation - {date_str}"

    campaign = Campaign(
        workspace_id=workspace_id,
        agent_id=agent.id,
        from_phone_number=phone_record.phone_number,
        name=resolved_name,
        ai_enabled=True,
        **{k: v for k, v in defaults.items() if k not in ("name", "ai_enabled")},
    )
    db.add(campaign)
    await db.flush()

    logger.info(
        "realtor_campaign_created",
        workspace_id=str(workspace_id),
        campaign_id=str(campaign.id),
        user_id=current_user.id,
    )

    # 6. Enroll imported contacts
    added_count = 0
    for contact in import_result.created_contacts:
        campaign_contact = CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact.id,
        )
        db.add(campaign_contact)
        added_count += 1

    campaign.total_contacts = added_count

    # 7. Start the campaign
    campaign.status = CampaignStatus.RUNNING
    campaign.started_at = datetime.now(UTC)

    # 8. Create and start drip campaign (automated multi-step reactivation)
    drip_ids = [c.id for c in import_result.created_contacts]
    await auto_create_drip_for_imports(db, workspace_id, drip_ids)

    await db.commit()
    await db.refresh(campaign)

    logger.info(
        "realtor_campaign_started",
        workspace_id=str(workspace_id),
        campaign_id=str(campaign.id),
        contacts=added_count,
    )

    return RealtorCampaignResponse(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        campaign_status=campaign.status,
        contacts_imported=import_result.successful,
        contacts_skipped=import_result.skipped_duplicates,
        contacts_failed=import_result.failed,
        phone_number_used=phone_record.phone_number,
        agent_id=agent.id,
        started_at=campaign.started_at,
    )


@router.post("/parse-calcom-url", response_model=ParseCalcomUrlResponse)
async def parse_calcom_url(
    request: ParseCalcomUrlRequest,
    current_user: CurrentUser,
    db: DB,
) -> ParseCalcomUrlResponse:
    """Parse a Cal.com booking URL and resolve the event_type_id.

    Extracts username and slug from the URL, then calls the Cal.com v2 API
    using the workspace's stored Cal.com API key (or the key supplied in the
    request body if none is stored yet).
    """
    workspace = await _get_user_workspace(current_user, db)

    match = _CALCOM_URL_RE.match(request.url.strip())
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "URL does not match expected Cal.com format: "
                "https://cal.com/{username}/{slug} or "
                "https://app.cal.com/{username}/{slug}"
            ),
        )

    username, slug = match.group(1), match.group(2)

    api_key = await _get_workspace_calcom_api_key(workspace.id, db)
    if api_key is None:
        api_key = request.api_key
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No Cal.com API key found for this workspace. "
                "Provide one via the api_key field or connect Cal.com in Settings first."
            ),
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{_CALCOM_V2_BASE}/event-types",
                params={"username": username, "slug": slug},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "cal-api-version": "2024-08-13",
                },
            )
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
        logger.error("calcom_parse_url_network_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Cal.com — check your API key",
        ) from exc

    if response.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Cal.com — check your API key",
        )

    if response.status_code != 200:
        logger.warning(
            "calcom_event_type_lookup_failed",
            status_code=response.status_code,
            username=username,
            slug=slug,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Cal.com — check your API key",
        )

    body = response.json()

    # Cal.com v2 returns { "status": "success", "data": [ { "id": ..., "slug": ... }, ... ] }
    event_types: list[dict] = []  # type: ignore[type-arg]
    data = body.get("data", [])
    if isinstance(data, list):
        event_types = data
    elif isinstance(data, dict):
        event_types = data.get("eventTypeGroups", []) or []

    matched_id: int | None = None
    for et in event_types:
        if isinstance(et, dict) and et.get("slug") == slug:
            matched_id = et.get("id")
            break

    if matched_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No event type with slug '{slug}' found for Cal.com user '{username}'. "
                "Double-check the URL."
            ),
        )

    logger.info(
        "calcom_url_parsed",
        workspace_id=str(workspace.id),
        username=username,
        slug=slug,
        event_type_id=matched_id,
    )

    return ParseCalcomUrlResponse(
        event_type_id=matched_id,
        slug=slug,
        username=username,
    )


@router.get("/verify-calcom", response_model=VerifyCalcomResponse)
async def verify_calcom(
    current_user: CurrentUser,
    api_key: str = Query(..., min_length=1, description="Cal.com API key to verify"),
) -> VerifyCalcomResponse:
    """Verify a Cal.com API key by calling the /me endpoint.

    Returns { valid: true, username: "..." } on success,
    or { valid: false, username: null } for an invalid key.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{_CALCOM_V1_BASE}/me",
                params={"apiKey": api_key},
            )
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
        logger.error("calcom_verify_network_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Cal.com — check your network connection",
        ) from exc

    if response.status_code == 401:
        return VerifyCalcomResponse(valid=False, username=None)

    if response.status_code != 200:
        logger.warning(
            "calcom_verify_unexpected_status",
            status_code=response.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Cal.com — check your network connection",
        )

    body = response.json()
    # Cal.com v1 /me returns { "user": { "username": "...", ... } }
    user_data = body.get("user") or body.get("data") or body
    username: str | None = None
    if isinstance(user_data, dict):
        username = user_data.get("username") or None

    logger.info("calcom_key_verified", username=username)

    return VerifyCalcomResponse(valid=True, username=username)
