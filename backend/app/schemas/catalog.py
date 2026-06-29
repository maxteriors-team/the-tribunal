"""Price book / catalog schemas.

Mirrors :mod:`app.schemas.quote` conventions (``float`` money fields,
``from_attributes`` responses). ``kind`` is constrained to the same set as the
``catalog_item_kind`` enum; server-managed fields (``id``, timestamps) are
response-only.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CatalogItemKind = Literal["service", "product"]


class CatalogItemBase(BaseModel):
    """Client-settable catalog item fields."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    sku: str | None = Field(default=None, max_length=100)
    kind: CatalogItemKind = "service"
    unit_price: float = Field(default=0.0, ge=0)
    taxable: bool = True
    is_active: bool = True


class CatalogItemCreate(CatalogItemBase):
    """Create a catalog item."""


class CatalogItemUpdate(BaseModel):
    """Update a catalog item (all fields optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    sku: str | None = Field(default=None, max_length=100)
    kind: CatalogItemKind | None = None
    unit_price: float | None = Field(default=None, ge=0)
    taxable: bool | None = None
    is_active: bool | None = None


class CatalogItemResponse(CatalogItemBase):
    """Catalog item as returned by the API."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedCatalogItems(BaseModel):
    """Paginated list of catalog items."""

    items: list[CatalogItemResponse]
    total: int
    page: int
    page_size: int
    pages: int
