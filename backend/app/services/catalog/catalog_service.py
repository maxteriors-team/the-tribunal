"""Price book / catalog business logic.

Plain workspace-scoped CRUD over :class:`app.models.catalog.CatalogItem`,
mirroring the lookup/pagination conventions of
:class:`app.services.quotes.quote_service.QuoteService` (``get_or_404`` +
``paginate`` + ``build_response``). The catalog has no lifecycle; ``is_active``
is a soft archive toggled through the normal update path.
"""

import uuid

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crud import get_or_404
from app.db.pagination import paginate
from app.models.catalog import CatalogItem
from app.schemas.catalog import (
    CatalogItemCreate,
    CatalogItemResponse,
    CatalogItemUpdate,
    PaginatedCatalogItems,
)

logger = structlog.get_logger()


class CatalogService:
    """Service for catalog (price book) CRUD."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="catalog_service")

    async def list_items(
        self,
        workspace_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        kind: str | None = None,
        search: str | None = None,
        include_inactive: bool = False,
    ) -> PaginatedCatalogItems:
        """List a workspace's catalog items, alphabetically.

        Active items only by default (pickers should never offer archived
        items); pass ``include_inactive`` for the management screen.
        """
        query = select(CatalogItem).where(CatalogItem.workspace_id == workspace_id)
        if not include_inactive:
            query = query.where(CatalogItem.is_active.is_(True))
        if kind:
            query = query.where(CatalogItem.kind == kind)
        if search:
            term = f"%{search.strip()}%"
            query = query.where(or_(CatalogItem.name.ilike(term), CatalogItem.sku.ilike(term)))
        query = query.order_by(CatalogItem.name.asc())

        result = await paginate(self.db, query, page=page, page_size=page_size)
        return result.build_response(
            item_model=CatalogItemResponse,
            response_builder=PaginatedCatalogItems,
        )

    async def create_item(
        self,
        workspace_id: uuid.UUID,
        item_in: CatalogItemCreate,
        *,
        created_by_id: int | None = None,
    ) -> CatalogItemResponse:
        """Create a catalog item."""
        item = CatalogItem(
            workspace_id=workspace_id,
            name=item_in.name,
            description=item_in.description,
            sku=item_in.sku,
            kind=item_in.kind,
            unit_price=item_in.unit_price,
            taxable=item_in.taxable,
            is_active=item_in.is_active,
            created_by_id=created_by_id,
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        self.log.info(
            "catalog_item_created",
            item_id=str(item.id),
            workspace_id=str(workspace_id),
            name=item.name,
        )
        return CatalogItemResponse.model_validate(item)

    async def get_item(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> CatalogItemResponse:
        """Fetch a single catalog item."""
        item = await get_or_404(self.db, CatalogItem, item_id, workspace_id=workspace_id)
        return CatalogItemResponse.model_validate(item)

    async def update_item(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        item_in: CatalogItemUpdate,
    ) -> CatalogItemResponse:
        """Update a catalog item. Only provided fields change."""
        item = await get_or_404(self.db, CatalogItem, item_id, workspace_id=workspace_id)
        for field in (
            "name",
            "description",
            "sku",
            "kind",
            "unit_price",
            "taxable",
            "is_active",
        ):
            value = getattr(item_in, field)
            if value is not None:
                setattr(item, field, value)
        await self.db.commit()
        await self.db.refresh(item)
        return CatalogItemResponse.model_validate(item)

    async def delete_item(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> None:
        """Permanently delete a catalog item.

        Safe because copying an item onto a quote/invoice snapshots its values;
        deleting the template never affects existing documents.
        """
        item = await get_or_404(self.db, CatalogItem, item_id, workspace_id=workspace_id)
        await self.db.delete(item)
        await self.db.commit()
