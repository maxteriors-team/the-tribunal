"""Phone number management endpoints."""

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DB, CanManageComms, CanReadCRM, CurrentUser
from app.core.config import settings
from app.db.pagination import paginate
from app.models.phone_number import PhoneNumber
from app.schemas.phone_number import (
    PaginatedPhoneNumbers,
    PhoneNumberInfoResponse,
    PhoneNumberResponse,
    PhoneNumberUpdate,
    PurchasePhoneNumberRequest,
    SearchPhoneNumbersRequest,
)
from app.services.telephony.telnyx import TelnyxSMSService

router = APIRouter()


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
    """List phone numbers (shared across workspaces for now)."""
    # Phone numbers are shared across workspaces - don't filter by workspace_id
    query = select(PhoneNumber)

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
    """Get a phone number by ID (shared across workspaces)."""
    # Phone numbers are shared across workspaces - don't filter by workspace_id
    result = await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.id == phone_number_id,
        )
    )
    phone_number = result.scalar_one_or_none()

    if not phone_number:
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

    update_data = phone_number_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(phone_number, field, value)

    await db.commit()
    await db.refresh(phone_number)

    return phone_number


@router.post("/search", response_model=list[PhoneNumberInfoResponse])
async def search_phone_numbers(
    workspace_id: uuid.UUID,
    request_data: SearchPhoneNumbersRequest,
    current_user: CurrentUser,
    membership: CanManageComms,
) -> list[PhoneNumberInfoResponse]:
    """Search for available phone numbers to purchase."""
    if not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telnyx not configured",
        )

    service = TelnyxSMSService(settings.telnyx_api_key)
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
    if not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telnyx not configured",
        )

    service = TelnyxSMSService(settings.telnyx_api_key)
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

    if not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telnyx not configured",
        )

    # Release from Telnyx if we have the provider ID
    if phone_number.telnyx_phone_number_id:
        service = TelnyxSMSService(settings.telnyx_api_key)
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
    if not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telnyx not configured",
        )

    service = TelnyxSMSService(settings.telnyx_api_key)
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
                is_active=True,
            )
            db.add(phone_number)
            synced += 1
        elif existing.workspace_id != workspace_id:
            # Phone number exists in another workspace - skip (shared phone numbers)
            pass

    await db.commit()
    return {"synced": synced}
