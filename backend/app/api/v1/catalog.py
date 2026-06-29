"""Price book / catalog management endpoints.

Thin transport layer over :class:`app.services.catalog.CatalogService`. Workspace
scoping and auth follow the same deps as ``quotes.py`` / ``invoices.py``. These
items are the source the quote / invoice line-item editors pull names and prices
from.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DB, CurrentUser, get_workspace
from app.api.service_errors import ServiceErrorRoute
from app.models.workspace import Workspace
from app.schemas.catalog import (
    CatalogItemCreate,
    CatalogItemResponse,
    CatalogItemUpdate,
    PaginatedCatalogItems,
)
from app.services.catalog import CatalogService

router = APIRouter(route_class=ServiceErrorRoute)


@router.get("", response_model=PaginatedCatalogItems)
async def list_catalog_items(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    kind: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    include_inactive: Annotated[bool, Query()] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> PaginatedCatalogItems:
    """List a workspace's catalog items (active only unless include_inactive)."""
    service = CatalogService(db)
    return await service.list_items(
        workspace_id,
        page=page,
        page_size=page_size,
        kind=kind,
        search=search,
        include_inactive=include_inactive,
    )


@router.post("", response_model=CatalogItemResponse, status_code=status.HTTP_201_CREATED)
async def create_catalog_item(
    workspace_id: uuid.UUID,
    item_in: CatalogItemCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> CatalogItemResponse:
    """Create a catalog item."""
    service = CatalogService(db)
    return await service.create_item(workspace_id, item_in, created_by_id=current_user.id)


@router.get("/{item_id}", response_model=CatalogItemResponse)
async def get_catalog_item(
    workspace_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> CatalogItemResponse:
    """Get a specific catalog item."""
    service = CatalogService(db)
    return await service.get_item(workspace_id, item_id)


@router.put("/{item_id}", response_model=CatalogItemResponse)
async def update_catalog_item(
    workspace_id: uuid.UUID,
    item_id: uuid.UUID,
    item_in: CatalogItemUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> CatalogItemResponse:
    """Update a catalog item's fields."""
    service = CatalogService(db)
    return await service.update_item(workspace_id, item_id, item_in)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalog_item(
    workspace_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a catalog item (templates are safe to delete; documents snapshot)."""
    service = CatalogService(db)
    await service.delete_item(workspace_id, item_id)
