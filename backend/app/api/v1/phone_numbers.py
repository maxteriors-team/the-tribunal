"""Phone number management endpoints."""

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CanManageComms, CanReadCRM, CurrentUser
from app.core.config import settings
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope
from app.models.agent import Agent
from app.models.lead_source import LeadSource, LeadSourceCampaign
from app.models.phone_number import PhoneNumber
from app.models.workspace import WorkspaceIntegration
from app.schemas.phone_number import (
    InboundCallConfigRequest,
    InboundCallReadinessResponse,
    InboundReadinessCheck,
    PaginatedPhoneNumbers,
    PhoneNumberInfoResponse,
    PhoneNumberResponse,
    PhoneNumberUpdate,
    PurchasePhoneNumberRequest,
    SearchPhoneNumbersRequest,
)
from app.services.telephony.inbound_call_readiness import (
    InboundCallReadiness,
    evaluate_inbound_call_readiness,
)
from app.services.telephony.telnyx import TelnyxSMSService

router = APIRouter()


async def _resolve_telnyx_api_key(db: AsyncSession, workspace_id: uuid.UUID) -> str | None:
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace_id,
            WorkspaceIntegration.integration_type == "telnyx",
            WorkspaceIntegration.is_active.is_(True),
        )
    )
    integration = result.scalar_one_or_none()
    credentials = integration.safe_credentials() if integration else None
    workspace_api_key = credentials.get("api_key") if credentials else None
    if isinstance(workspace_api_key, str) and workspace_api_key.strip():
        return workspace_api_key.strip()
    return settings.telnyx_api_key


def _telnyx_not_configured(action: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "telnyx_provider_not_configured",
            "message": f"Connect Telnyx before you {action}.",
            "details": {"provider": "telnyx", "action": action},
        },
    )


async def _validate_tracking_mapping(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    lead_source_id: uuid.UUID | None,
    lead_source_campaign_id: uuid.UUID | None,
) -> None:
    """Reject cross-workspace or mismatched source/campaign mappings."""
    if lead_source_id is None:
        if lead_source_campaign_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A campaign requires a lead source",
            )
        return

    source_result = await db.execute(
        select(LeadSource.id).where(
            LeadSource.id == lead_source_id,
            LeadSource.workspace_id == workspace_id,
        )
    )
    if source_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead source not found",
        )

    if lead_source_campaign_id is None:
        return

    campaign_result = await db.execute(
        select(LeadSourceCampaign.id).where(
            LeadSourceCampaign.id == lead_source_campaign_id,
            LeadSourceCampaign.workspace_id == workspace_id,
            LeadSourceCampaign.lead_source_id == lead_source_id,
        )
    )
    if campaign_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found for this lead source",
        )


async def _get_assignable_agent(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> Agent:
    """Resolve only an active voice agent owned by the current workspace."""
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.workspace_id == workspace_id,
            Agent.is_active.is_(True),
            Agent.channel_mode.in_(("voice", "both")),
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice agent not found",
        )
    return agent


def _readiness_response(
    phone_number: PhoneNumber,
    readiness: InboundCallReadiness,
) -> InboundCallReadinessResponse:
    """Serialize bounded readiness details without provider or credential data."""
    return InboundCallReadinessResponse(
        phone_number_id=phone_number.id,
        ready=readiness.ready,
        enabled=phone_number.inbound_ai_enabled,
        assigned_agent_id=phone_number.assigned_agent_id,
        fallback_configured=bool(phone_number.inbound_fallback_number),
        transfer_destination_configured=bool(
            readiness.agent and readiness.agent.transfer_destination_number
        ),
        checks=[
            InboundReadinessCheck(
                code=check.code,
                ready=check.ready,
                message=check.message,
            )
            for check in readiness.checks
        ],
    )


async def _deactivate_inbound_calling(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    phone_number: PhoneNumber,
    request_data: InboundCallConfigRequest,
) -> InboundCallReadinessResponse:
    """Persist the kill switch before applying optional inactive configuration."""
    phone_number.inbound_ai_enabled = False
    await db.commit()

    agent = None
    if "assigned_agent_id" in request_data.model_fields_set:
        phone_number.assigned_agent_id = request_data.assigned_agent_id
        if request_data.assigned_agent_id is not None:
            agent = await _get_assignable_agent(db, workspace_id, request_data.assigned_agent_id)
    elif phone_number.assigned_agent_id is not None:
        agent = await _get_assignable_agent(db, workspace_id, phone_number.assigned_agent_id)

    if "fallback_number" in request_data.model_fields_set:
        phone_number.inbound_fallback_number = request_data.fallback_number
    if "transfer_destination_number" in request_data.model_fields_set:
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Choose a voice agent before configuring human transfer.",
            )
        agent.transfer_destination_number = request_data.transfer_destination_number
    await db.commit()

    readiness = await evaluate_inbound_call_readiness(
        db,
        workspace_id=workspace_id,
        phone_number=phone_number,
        assigned_agent_id=phone_number.assigned_agent_id,
        fallback_number=phone_number.inbound_fallback_number,
        transfer_destination_number=(
            agent.transfer_destination_number if agent is not None else None
        ),
    )
    return _readiness_response(phone_number, readiness)


@router.get("", response_model=PaginatedPhoneNumbers)
async def list_phone_numbers(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    sms_enabled: bool | None = None,
    active_only: bool = True,
) -> PaginatedPhoneNumbers:
    """List the workspace's phone numbers."""
    query = apply_workspace_scope(
        select(PhoneNumber).options(
            selectinload(PhoneNumber.lead_source),
            selectinload(PhoneNumber.lead_source_campaign),
        ),
        PhoneNumber,
        workspace_id,
    )

    if active_only:
        query = query.where(PhoneNumber.is_active.is_(True))

    if sms_enabled is not None:
        query = query.where(PhoneNumber.sms_enabled == sms_enabled)

    query = query.order_by(PhoneNumber.created_at.desc())
    result = await paginate(db, query, page=page, page_size=page_size)

    return PaginatedPhoneNumbers(**result.to_response(PhoneNumberResponse))


@router.get("/{phone_number_id}", response_model=PhoneNumberResponse)
async def get_phone_number(
    workspace_id: uuid.UUID,
    phone_number_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> PhoneNumber:
    """Get one of the workspace's phone numbers by ID."""
    result = await db.execute(
        select(PhoneNumber)
        .options(
            selectinload(PhoneNumber.lead_source),
            selectinload(PhoneNumber.lead_source_campaign),
        )
        .where(
            PhoneNumber.id == phone_number_id,
            PhoneNumber.workspace_id == workspace_id,
        )
    )
    phone_number = result.scalar_one_or_none()
    if phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phone number not found",
        )
    return phone_number


@router.put("/{phone_number_id}", response_model=PhoneNumberResponse)
async def update_phone_number(
    workspace_id: uuid.UUID,
    phone_number_id: uuid.UUID,
    phone_number_in: PhoneNumberUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanManageComms,
) -> PhoneNumber:
    """Update a phone number."""
    result = await db.execute(
        select(PhoneNumber)
        .options(
            selectinload(PhoneNumber.lead_source),
            selectinload(PhoneNumber.lead_source_campaign),
        )
        .where(
            PhoneNumber.id == phone_number_id,
            PhoneNumber.workspace_id == workspace_id,
        )
    )
    phone_number = result.scalar_one_or_none()

    if not phone_number:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phone number not found",
        )

    update_data = phone_number_in.model_dump(exclude_unset=True)
    if "assigned_agent_id" in update_data:
        assigned_agent_id = update_data["assigned_agent_id"]
        # Any assignment change must pass the explicit readiness/activation flow again.
        update_data["inbound_ai_enabled"] = False
        if assigned_agent_id is not None:
            await _get_assignable_agent(db, workspace_id, assigned_agent_id)

    source_supplied = "lead_source_id" in update_data
    campaign_supplied = "lead_source_campaign_id" in update_data

    if source_supplied or campaign_supplied:
        target_source_id = update_data.get("lead_source_id", phone_number.lead_source_id)
        if (
            source_supplied
            and target_source_id != phone_number.lead_source_id
            and not campaign_supplied
        ):
            update_data["lead_source_campaign_id"] = None

        target_campaign_id = update_data.get(
            "lead_source_campaign_id", phone_number.lead_source_campaign_id
        )
        if target_source_id is None:
            update_data["lead_source_campaign_id"] = None
            target_campaign_id = None

        await _validate_tracking_mapping(db, workspace_id, target_source_id, target_campaign_id)

    if "tracking_label" in update_data and update_data["tracking_label"] is not None:
        update_data["tracking_label"] = update_data["tracking_label"].strip() or None

    for field, value in update_data.items():
        setattr(phone_number, field, value)

    await db.commit()
    await db.refresh(phone_number, attribute_names=["lead_source", "lead_source_campaign"])

    return phone_number


@router.get(
    "/{phone_number_id}/inbound-readiness",
    response_model=InboundCallReadinessResponse,
)
async def get_inbound_readiness(
    workspace_id: uuid.UUID,
    phone_number_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanManageComms,
) -> InboundCallReadinessResponse:
    """Return non-sensitive prerequisites for AI-first inbound activation."""
    result = await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.id == phone_number_id,
            PhoneNumber.workspace_id == workspace_id,
        )
    )
    phone_number = result.scalar_one_or_none()
    if phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phone number not found",
        )

    readiness = await evaluate_inbound_call_readiness(
        db,
        workspace_id=workspace_id,
        phone_number=phone_number,
        assigned_agent_id=phone_number.assigned_agent_id,
        fallback_number=phone_number.inbound_fallback_number,
        transfer_destination_number=None,
    )
    return _readiness_response(phone_number, readiness)


@router.put(
    "/{phone_number_id}/inbound-config",
    response_model=InboundCallReadinessResponse,
)
async def configure_inbound_calling(
    workspace_id: uuid.UUID,
    phone_number_id: uuid.UUID,
    request_data: InboundCallConfigRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanManageComms,
) -> InboundCallReadinessResponse:
    """Configure and explicitly activate or deactivate AI-first inbound routing."""
    result = await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.id == phone_number_id,
            PhoneNumber.workspace_id == workspace_id,
        )
    )
    phone_number = result.scalar_one_or_none()
    if phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phone number not found",
        )

    if not request_data.enabled:
        return await _deactivate_inbound_calling(db, workspace_id, phone_number, request_data)

    # Keep activation off until every local and provider-side prerequisite succeeds.
    phone_number.inbound_ai_enabled = False
    await db.commit()
    effective_fallback_number = (
        request_data.fallback_number
        if "fallback_number" in request_data.model_fields_set
        else phone_number.inbound_fallback_number
    )
    readiness = await evaluate_inbound_call_readiness(
        db,
        workspace_id=workspace_id,
        phone_number=phone_number,
        assigned_agent_id=request_data.assigned_agent_id,
        fallback_number=effective_fallback_number,
        transfer_destination_number=request_data.transfer_destination_number,
    )
    if not readiness.ready:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "inbound_calling_not_ready",
                "message": "Complete every inbound calling prerequisite.",
                "checks": [
                    {"code": check.code, "ready": check.ready, "message": check.message}
                    for check in readiness.checks
                ],
            },
        )

    provider_number_id = phone_number.telnyx_phone_number_id
    if provider_number_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Phone number is not linked to Telnyx",
        )
    telnyx = TelnyxSMSService(settings.telnyx_api_key)
    try:
        configured = await telnyx.configure_phone_number(
            provider_number_id,
            connection_id=settings.telnyx_connection_id,
        )
    finally:
        await telnyx.close()
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "telnyx_voice_activation_failed",
                "message": "Telnyx could not activate inbound voice routing.",
            },
        )

    if readiness.agent is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Voice agent not found",
        )
    phone_number.assigned_agent_id = readiness.agent.id
    if "fallback_number" in request_data.model_fields_set:
        phone_number.inbound_fallback_number = request_data.fallback_number
    if "transfer_destination_number" in request_data.model_fields_set:
        readiness.agent.transfer_destination_number = request_data.transfer_destination_number
    phone_number.inbound_ai_enabled = True
    await db.commit()
    return _readiness_response(phone_number, readiness)


@router.post("/search", response_model=list[PhoneNumberInfoResponse])
async def search_phone_numbers(
    workspace_id: uuid.UUID,
    request_data: SearchPhoneNumbersRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanManageComms,
) -> list[PhoneNumberInfoResponse]:
    """Search for available phone numbers to purchase."""
    api_key = await _resolve_telnyx_api_key(db, workspace_id)
    if not api_key:
        raise _telnyx_not_configured("search for phone numbers")

    service = TelnyxSMSService(api_key)
    try:
        numbers = await service.search_phone_numbers(
            country=request_data.country,
            area_code=request_data.area_code,
            contains=request_data.contains,
            limit=request_data.limit,
        )
        return [
            PhoneNumberInfoResponse(
                id=n.id,
                phone_number=n.phone_number,
                friendly_name=n.friendly_name,
                capabilities=n.capabilities,
            )
            for n in numbers
        ]
    finally:
        await service.close()


@router.post("/purchase", response_model=PhoneNumberResponse)
async def purchase_phone_number(
    workspace_id: uuid.UUID,
    request_data: PurchasePhoneNumberRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanManageComms,
) -> PhoneNumber:
    """Purchase a phone number from Telnyx."""
    api_key = await _resolve_telnyx_api_key(db, workspace_id)
    if not api_key:
        raise _telnyx_not_configured("purchase a phone number")

    service = TelnyxSMSService(api_key)
    try:
        # Purchase from Telnyx
        purchased = await service.purchase_phone_number(request_data.phone_number)

        # Create database record
        phone_number = PhoneNumber(
            workspace_id=workspace_id,
            phone_number=purchased.phone_number,
            telnyx_phone_number_id=purchased.id,
            sms_enabled=True,
            voice_enabled=True,
            mms_enabled=True,
            is_active=True,
        )
        db.add(phone_number)
        await db.commit()
        await db.refresh(phone_number)

        return phone_number
    finally:
        await service.close()


@router.delete("/{phone_number_id}")
async def release_phone_number(
    workspace_id: uuid.UUID,
    phone_number_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanManageComms,
) -> dict[str, bool]:
    """Release a phone number back to Telnyx."""
    result = await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.id == phone_number_id,
            PhoneNumber.workspace_id == workspace_id,
        )
    )
    phone_number = result.scalar_one_or_none()

    if not phone_number:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phone number not found",
        )

    api_key = await _resolve_telnyx_api_key(db, workspace_id)
    if not api_key:
        raise _telnyx_not_configured("release a phone number")

    # Release from Telnyx if we have the provider ID
    if phone_number.telnyx_phone_number_id:
        service = TelnyxSMSService(api_key)
        try:
            await service.release_phone_number(phone_number.telnyx_phone_number_id)
        finally:
            await service.close()

    # Delete from database
    await db.delete(phone_number)
    await db.commit()

    return {"success": True}


@router.post("/sync")
async def sync_phone_numbers(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanManageComms,
) -> dict[str, int]:
    """Sync phone numbers from Telnyx account."""
    api_key = await _resolve_telnyx_api_key(db, workspace_id)
    if not api_key:
        raise _telnyx_not_configured("sync phone numbers")

    service = TelnyxSMSService(api_key)
    try:
        telnyx_numbers = await service.list_phone_numbers()
    finally:
        await service.close()

    synced = 0
    for tn in telnyx_numbers:
        # Check if phone number already exists globally (unique constraint is on phone_number)
        result = await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.phone_number == tn.phone_number,
            )
        )
        existing = result.scalar_one_or_none()

        if not existing:
            # Phone number doesn't exist anywhere - create it for this workspace
            phone_number = PhoneNumber(
                workspace_id=workspace_id,
                phone_number=tn.phone_number,
                friendly_name=tn.friendly_name,
                telnyx_phone_number_id=tn.id,
                sms_enabled=tn.capabilities.get("sms", False) if tn.capabilities else False,
                voice_enabled=tn.capabilities.get("voice", False) if tn.capabilities else False,
                mms_enabled=tn.capabilities.get("sms", False) if tn.capabilities else False,
                is_active=True,
            )
            db.add(phone_number)
            synced += 1
        elif existing.workspace_id != workspace_id:
            # Phone number exists in another workspace - skip (shared phone numbers)
            pass

    await db.commit()
    return {"synced": synced}
