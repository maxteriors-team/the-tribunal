"""Offer management endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.crud import get_or_404
from app.api.deps import DB, CurrentUser, get_workspace
from app.core.encryption import hash_phone, hash_value
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope, select_workspace_owned
from app.models.contact import Contact
from app.models.lead_magnet import LeadMagnet
from app.models.lead_magnet_lead import LeadMagnetLead
from app.models.offer import Offer
from app.models.offer_lead_magnet import OfferLeadMagnet
from app.models.workspace import Workspace
from app.schemas.lead_magnet import LeadMagnetResponse
from app.schemas.offer import (
    GeneratedOfferContent,
    OfferCreate,
    OfferGenerationRequest,
    OfferResponse,
    OfferResponseWithLeadMagnets,
    OfferUpdate,
    OptInRequest,
    OptInResponse,
    PaginatedOffers,
    PublicOfferResponse,
    ValueStackItem,
)
from app.services.ai.offer_generator import generate_offer_content

router = APIRouter()
public_router = APIRouter()


@router.post("/generate", response_model=GeneratedOfferContent)
async def generate_offer_ai(
    workspace_id: uuid.UUID,
    request: OfferGenerationRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> GeneratedOfferContent:
    """Generate offer content using AI with Hormozi framework."""
    result = await generate_offer_content(
        business_type=request.business_type,
        target_audience=request.target_audience,
        main_offer=request.main_offer,
        price_point=request.price_point,
        desired_outcome=request.desired_outcome,
        pain_points=request.pain_points,
        unique_mechanism=request.unique_mechanism,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to generate offer content"),
        )

    return GeneratedOfferContent(**result)


@router.get("", response_model=PaginatedOffers)
async def list_offers(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    active_only: bool = False,
) -> PaginatedOffers:
    """List offers in a workspace."""
    query = select_workspace_owned(Offer, workspace_id)

    if active_only:
        query = query.where(Offer.is_active.is_(True))

    query = query.order_by(Offer.created_at.desc())
    result = await paginate(db, query, page=page, page_size=page_size)

    return PaginatedOffers(**result.to_response(OfferResponse))


@router.post("", response_model=OfferResponse, status_code=status.HTTP_201_CREATED)
async def create_offer(
    workspace_id: uuid.UUID,
    offer_in: OfferCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Offer:
    """Create a new offer."""
    offer = Offer(
        workspace_id=workspace_id,
        **offer_in.model_dump(),
    )
    db.add(offer)
    await db.commit()
    await db.refresh(offer)

    return offer


@router.get("/{offer_id}", response_model=OfferResponse)
async def get_offer(
    workspace_id: uuid.UUID,
    offer_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Offer:
    """Get an offer by ID."""
    return await get_or_404(db, Offer, offer_id, workspace_id=workspace_id)


@router.put("/{offer_id}", response_model=OfferResponse)
async def update_offer(
    workspace_id: uuid.UUID,
    offer_id: uuid.UUID,
    offer_in: OfferUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Offer:
    """Update an offer."""
    offer = await get_or_404(db, Offer, offer_id, workspace_id=workspace_id)

    # Update fields
    update_data = offer_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(offer, field, value)

    await db.commit()
    await db.refresh(offer)

    return offer


@router.delete("/{offer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_offer(
    workspace_id: uuid.UUID,
    offer_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete an offer."""
    offer = await get_or_404(db, Offer, offer_id, workspace_id=workspace_id)
    await db.delete(offer)
    await db.commit()


@router.get("/{offer_id}/with-lead-magnets", response_model=OfferResponseWithLeadMagnets)
async def get_offer_with_lead_magnets(
    workspace_id: uuid.UUID,
    offer_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OfferResponseWithLeadMagnets:
    """Get an offer with its attached lead magnets."""
    offer = await get_or_404(
        db,
        Offer,
        offer_id,
        workspace_id=workspace_id,
        options=[selectinload(Offer.offer_lead_magnets).selectinload(OfferLeadMagnet.lead_magnet)],
    )

    # Extract lead magnets and calculate total value
    lead_magnets = [
        LeadMagnetResponse.model_validate(olm.lead_magnet)
        for olm in sorted(offer.offer_lead_magnets, key=lambda x: x.sort_order)
    ]

    # Calculate total value from value stack and lead magnets
    total_value = 0.0
    if offer.value_stack_items:
        for item in offer.value_stack_items:
            if item.get("included", True):
                value = item.get("value", 0)
                if isinstance(value, (int, float)):
                    total_value += value
    for lm in lead_magnets:
        if lm.estimated_value:
            total_value += lm.estimated_value

    return OfferResponseWithLeadMagnets(
        **OfferResponse.model_validate(offer).model_dump(),
        lead_magnets=lead_magnets,
        total_value=total_value if total_value > 0 else None,
    )


@router.post("/{offer_id}/lead-magnets", response_model=OfferResponseWithLeadMagnets)
async def attach_lead_magnets(
    workspace_id: uuid.UUID,
    offer_id: uuid.UUID,
    lead_magnet_ids: list[uuid.UUID],
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OfferResponseWithLeadMagnets:
    """Attach lead magnets to an offer."""
    # Verify offer exists
    await get_or_404(db, Offer, offer_id, workspace_id=workspace_id)

    # Verify all lead magnets exist in this workspace
    result = await db.execute(
        select_workspace_owned(
            LeadMagnet,
            workspace_id,
            LeadMagnet.id.in_(lead_magnet_ids),
        )
    )
    found_magnets = {lm.id for lm in result.scalars().all()}

    missing = set(lead_magnet_ids) - found_magnets
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead magnets not found: {missing}",
        )

    # Get current max sort order
    max_order_result = await db.execute(
        select(func.max(OfferLeadMagnet.sort_order)).where(OfferLeadMagnet.offer_id == offer_id)
    )
    max_order: int = max_order_result.scalar() or 0

    # Attach lead magnets (skip if already attached)
    result = await db.execute(
        select(OfferLeadMagnet.lead_magnet_id).where(OfferLeadMagnet.offer_id == offer_id)
    )
    existing_ids = {row[0] for row in result.all()}

    for idx, lm_id in enumerate(lead_magnet_ids):
        if lm_id not in existing_ids:
            association = OfferLeadMagnet(
                offer_id=offer_id,
                lead_magnet_id=lm_id,
                sort_order=max_order + idx + 1,
                is_bonus=True,
            )
            db.add(association)

    await db.commit()

    # Return updated offer with lead magnets
    return await get_offer_with_lead_magnets(
        workspace_id=workspace_id,
        offer_id=offer_id,
        current_user=current_user,
        db=db,
        workspace=workspace,
    )


@router.delete("/{offer_id}/lead-magnets/{lead_magnet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_lead_magnet(
    workspace_id: uuid.UUID,
    offer_id: uuid.UUID,
    lead_magnet_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Detach a lead magnet from an offer."""
    # Verify offer exists in workspace
    await get_or_404(db, Offer, offer_id, workspace_id=workspace_id)

    # Find and delete the association
    result = await db.execute(
        select(OfferLeadMagnet).where(
            OfferLeadMagnet.offer_id == offer_id,
            OfferLeadMagnet.lead_magnet_id == lead_magnet_id,
        )
    )
    association = result.scalar_one_or_none()

    if not association:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead magnet not attached to this offer",
        )

    await db.delete(association)
    await db.commit()


@router.put("/{offer_id}/lead-magnets/reorder", response_model=OfferResponseWithLeadMagnets)
async def reorder_lead_magnets(
    workspace_id: uuid.UUID,
    offer_id: uuid.UUID,
    lead_magnet_ids: list[uuid.UUID],
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> OfferResponseWithLeadMagnets:
    """Reorder lead magnets attached to an offer."""
    # Verify offer exists
    await get_or_404(db, Offer, offer_id, workspace_id=workspace_id)

    # Bulk fetch all associations in a single query, then update sort order in memory
    assoc_result = await db.execute(
        select(OfferLeadMagnet).where(
            OfferLeadMagnet.offer_id == offer_id,
            OfferLeadMagnet.lead_magnet_id.in_(lead_magnet_ids),
        )
    )
    associations_by_lm_id: dict[uuid.UUID, OfferLeadMagnet] = {
        assoc.lead_magnet_id: assoc for assoc in assoc_result.scalars().all()
    }

    for idx, lm_id in enumerate(lead_magnet_ids):
        association = associations_by_lm_id.get(lm_id)
        if association is not None:
            association.sort_order = idx

    await db.commit()

    return await get_offer_with_lead_magnets(
        workspace_id=workspace_id,
        offer_id=offer_id,
        current_user=current_user,
        db=db,
        workspace=workspace,
    )


# Public Routes (no authentication required)
@public_router.get("/{slug}", response_model=PublicOfferResponse)
async def get_public_offer(
    slug: str,
    db: DB,
) -> PublicOfferResponse:
    """Get a public offer by its slug."""
    result = await db.execute(
        select(Offer)
        .options(selectinload(Offer.offer_lead_magnets).selectinload(OfferLeadMagnet.lead_magnet))
        .where(
            Offer.public_slug == slug,
            Offer.is_public.is_(True),
            Offer.is_active.is_(True),
        )
    )
    offer = result.scalar_one_or_none()

    if not offer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offer not found",
        )

    # Increment page views
    offer.page_views += 1
    await db.commit()

    # Build lead magnets list
    lead_magnets = [
        LeadMagnetResponse.model_validate(olm.lead_magnet)
        for olm in sorted(offer.offer_lead_magnets, key=lambda x: x.sort_order)
    ]

    # Calculate total value
    total_value = 0.0
    if offer.value_stack_items:
        for item in offer.value_stack_items:
            if item.get("included", True):
                value = item.get("value", 0)
                if isinstance(value, (int, float)):
                    total_value += value
    for lm in lead_magnets:
        if lm.estimated_value:
            total_value += lm.estimated_value

    # Convert raw dicts to ValueStackItem models
    value_stack: list[ValueStackItem] | None = None
    if offer.value_stack_items:
        value_stack = [ValueStackItem.model_validate(item) for item in offer.value_stack_items]

    return PublicOfferResponse(
        name=offer.name,
        headline=offer.headline,
        subheadline=offer.subheadline,
        description=offer.description,
        regular_price=offer.regular_price,
        offer_price=offer.offer_price,
        savings_amount=offer.savings_amount,
        guarantee_type=offer.guarantee_type,
        guarantee_days=offer.guarantee_days,
        guarantee_text=offer.guarantee_text,
        urgency_type=offer.urgency_type,
        urgency_text=offer.urgency_text,
        scarcity_count=offer.scarcity_count,
        value_stack_items=value_stack,
        cta_text=offer.cta_text,
        cta_subtext=offer.cta_subtext,
        lead_magnets=lead_magnets,
        total_value=total_value if total_value > 0 else None,
        require_email=offer.require_email,
        require_phone=offer.require_phone,
        require_name=offer.require_name,
    )


@public_router.post("/{slug}/opt-in", response_model=OptInResponse)
async def submit_offer_optin(
    slug: str,
    optin: OptInRequest,
    db: DB,
) -> OptInResponse:
    """Submit an opt-in for a public offer."""
    # Get the offer
    result = await db.execute(
        select(Offer).where(
            Offer.public_slug == slug,
            Offer.is_public.is_(True),
            Offer.is_active.is_(True),
        )
    )
    offer = result.scalar_one_or_none()

    if not offer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offer not found",
        )

    # Validate required fields
    if offer.require_email and not optin.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required",
        )
    if offer.require_phone and not optin.phone_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number is required",
        )
    if offer.require_name and not optin.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name is required",
        )

    # Try to find or create contact
    contact: Contact | None = None
    if optin.email:
        contact_result = await db.execute(
            apply_workspace_scope(select(Contact), Contact, offer.workspace_id)
            .where(Contact.email_hash == hash_value(optin.email))
            .limit(1)
        )
        # first() (not scalar_one_or_none): earlier opt-ins under the broken
        # lookup may have created duplicate contacts sharing this email_hash.
        contact = contact_result.scalars().first()

    if not contact and optin.phone_number:
        contact_result = await db.execute(
            apply_workspace_scope(select(Contact), Contact, offer.workspace_id)
            .where(Contact.phone_hash == hash_phone(optin.phone_number))
            .limit(1)
        )
        contact = contact_result.scalars().first()

    if not contact:
        # Create new contact
        name_parts = (optin.name or "").split(" ", 1)
        first_name = name_parts[0] if name_parts else "Unknown"
        last_name = name_parts[1] if len(name_parts) > 1 else None

        contact = Contact(
            workspace_id=str(offer.workspace_id),
            first_name=first_name,
            last_name=last_name,
            email=optin.email,
            phone_number=optin.phone_number,
            status="new",
            notes=f"Opted in via offer: {offer.name}",
        )
        db.add(contact)
        await db.flush()

    # Create lead magnet lead record for each attached lead magnet
    lead_magnet_lead_id: uuid.UUID | None = None
    olm_result = await db.execute(
        select(OfferLeadMagnet).where(OfferLeadMagnet.offer_id == offer.id)
    )
    offer_lead_magnets = olm_result.scalars().all()

    for olm in offer_lead_magnets:
        lead = LeadMagnetLead(
            lead_magnet_id=olm.lead_magnet_id,
            workspace_id=offer.workspace_id,
            email=optin.email,
            phone_number=optin.phone_number,
            name=optin.name,
            contact_id=contact.id if contact else None,
            source_offer_id=offer.id,
            delivered=False,
        )
        db.add(lead)
        if lead_magnet_lead_id is None:
            await db.flush()
            lead_magnet_lead_id = lead.id

    # Increment opt-ins counter
    offer.opt_ins += 1

    await db.commit()

    return OptInResponse(
        success=True,
        message="Thank you for signing up!",
        contact_id=contact.id if contact else None,
        lead_magnet_lead_id=lead_magnet_lead_id,
    )
