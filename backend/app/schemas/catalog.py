"""Price book / catalog schemas.

Mirrors :mod:`app.schemas.quote` conventions (``float`` money fields,
``from_attributes`` responses). ``kind`` is constrained to the same set as the
``catalog_item_kind`` enum; server-managed fields (``id``, timestamps) are
response-only.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CatalogItemKind = Literal["service", "product"]


class CatalogComponent(BaseModel):
    """One part in a catalog item's SKU bill-of-materials (fulfillment sheet).

    Internal-only: the qty is *per unit* of the parent item, so a fixture that
    ships as a body + a lamp lists both here and the fulfillment sheet multiplies
    by the quantity on the proposal.
    """

    sku: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    qty: float = Field(default=1.0, ge=0)


class CatalogItemBase(BaseModel):
    """Client-settable catalog item fields."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    sku: str | None = Field(default=None, max_length=100)
    kind: CatalogItemKind = "service"
    unit_price: float = Field(default=0.0, ge=0)
    taxable: bool = True
    is_active: bool = True
    # Free-form flags a fixture/service carries beyond price (e.g. transformer,
    # per-linear-foot). Drives config behaviour with no new columns.
    attributes: dict[str, Any] | None = None
    # Internal SKU bill-of-materials for the fulfillment sheet (never client-facing).
    components: list[CatalogComponent] | None = None


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
    attributes: dict[str, Any] | None = None
    components: list[CatalogComponent] | None = None


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
