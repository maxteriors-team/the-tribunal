"""Message template management endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, get_workspace, require_route_capabilities
from app.core.permissions import Capability
from app.db.pagination import paginate
from app.models.message_template import MessageTemplate
from app.models.workspace import Workspace
from app.schemas.message_template import (
    MessageTemplateCreate,
    MessageTemplateResponse,
    MessageTemplateUpdate,
    PaginatedMessageTemplates,
)

router = APIRouter(
    dependencies=[
        Depends(require_route_capabilities(Capability.CRM_READ, Capability.OUTREACH_WRITE))
    ]
)


@router.get("", response_model=PaginatedMessageTemplates)
async def list_message_templates(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> PaginatedMessageTemplates:
    """List message templates in a workspace."""
    query = select(MessageTemplate).where(MessageTemplate.workspace_id == workspace_id)

    query = query.order_by(MessageTemplate.created_at.desc())
    result = await paginate(db, query, page=page, page_size=page_size)

    return PaginatedMessageTemplates(**result.to_response(MessageTemplateResponse))


@router.post("", response_model=MessageTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_message_template(
    workspace_id: uuid.UUID,
    template_in: MessageTemplateCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> MessageTemplate:
    """Create a new message template."""
    template = MessageTemplate(
        workspace_id=workspace_id,
        **template_in.model_dump(),
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)

    return template


@router.get("/{template_id}", response_model=MessageTemplateResponse)
async def get_message_template(
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> MessageTemplate:
    """Get a message template by ID."""
    result = await db.execute(
        select(MessageTemplate).where(
            MessageTemplate.id == template_id,
            MessageTemplate.workspace_id == workspace_id,
        )
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message template not found",
        )

    return template


@router.put("/{template_id}", response_model=MessageTemplateResponse)
async def update_message_template(
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
    template_in: MessageTemplateUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> MessageTemplate:
    """Update a message template."""
    result = await db.execute(
        select(MessageTemplate).where(
            MessageTemplate.id == template_id,
            MessageTemplate.workspace_id == workspace_id,
        )
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message template not found",
        )

    update_data = template_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)

    await db.commit()
    await db.refresh(template)

    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message_template(
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a message template."""
    result = await db.execute(
        select(MessageTemplate).where(
            MessageTemplate.id == template_id,
            MessageTemplate.workspace_id == workspace_id,
        )
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message template not found",
        )

    await db.delete(template)
    await db.commit()
