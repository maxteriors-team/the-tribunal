"""Lead Sources CRUD endpoints."""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, get_workspace
from app.core.config import settings
from app.models.lead_source import LeadSource
from app.schemas.lead_source import LeadSourceCreate, LeadSourceResponse, LeadSourceUpdate

router = APIRouter()


def _to_response(ls: LeadSource) -> LeadSourceResponse:
    """Convert a LeadSource model to response with computed endpoint_url."""
    api_base = settings.api_base_url or "http://localhost:8000"
    return LeadSourceResponse(
        id=ls.id,
        workspace_id=ls.workspace_id,
        name=ls.name,
        public_key=ls.public_key,
        allowed_domains=ls.allowed_domains,
        enabled=ls.enabled,
        action=ls.action,
        action_config=ls.action_config,
        created_at=ls.created_at,
        updated_at=ls.updated_at,
        endpoint_url=f"{api_base}/api/v1/p/leads/{ls.public_key}",
    )


@router.get("", response_model=list[LeadSourceResponse])
async def list_lead_sources(
    request: Request,
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> list[LeadSourceResponse]:
    """List all lead sources for a workspace."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSource)
        .where(LeadSource.workspace_id == workspace_id)
        .order_by(LeadSource.created_at.desc())
    )
    sources = list(result.scalars().all())
    return [_to_response(s) for s in sources]


@router.post("", response_model=LeadSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_lead_source(
    request: Request,
    workspace_id: uuid.UUID,
    body: LeadSourceCreate,
    current_user: CurrentUser,
    db: DB,
) -> LeadSourceResponse:
    """Create a new lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    lead_source = LeadSource(
        workspace_id=workspace_id,
        name=body.name,
        allowed_domains=body.allowed_domains,
        action=body.action,
        action_config=body.action_config,
    )
    db.add(lead_source)
    await db.flush()
    await db.refresh(lead_source)
    await db.commit()

    return _to_response(lead_source)


@router.get("/{lead_source_id}", response_model=LeadSourceResponse)
async def get_lead_source(
    request: Request,
    workspace_id: uuid.UUID,
    lead_source_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> LeadSourceResponse:
    """Get a single lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSource).where(
            LeadSource.id == lead_source_id,
            LeadSource.workspace_id == workspace_id,
        )
    )
    lead_source = result.scalar_one_or_none()
    if not lead_source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found")

    return _to_response(lead_source)


@router.put("/{lead_source_id}", response_model=LeadSourceResponse)
async def update_lead_source(
    request: Request,
    workspace_id: uuid.UUID,
    lead_source_id: uuid.UUID,
    body: LeadSourceUpdate,
    current_user: CurrentUser,
    db: DB,
) -> LeadSourceResponse:
    """Update a lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSource).where(
            LeadSource.id == lead_source_id,
            LeadSource.workspace_id == workspace_id,
        )
    )
    lead_source = result.scalar_one_or_none()
    if not lead_source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(lead_source, field, value)

    await db.flush()
    await db.refresh(lead_source)
    await db.commit()

    return _to_response(lead_source)


@router.delete("/{lead_source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_source(
    request: Request,
    workspace_id: uuid.UUID,
    lead_source_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> None:
    """Delete a lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSource).where(
            LeadSource.id == lead_source_id,
            LeadSource.workspace_id == workspace_id,
        )
    )
    lead_source = result.scalar_one_or_none()
    if not lead_source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found")

    await db.delete(lead_source)
    await db.commit()
