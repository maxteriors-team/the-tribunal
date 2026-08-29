"""Price book / catalog models.

A workspace-scoped library of reusable products and services. A
:class:`CatalogItem` holds the canonical name, default unit price, and tax flag
that quote / invoice / job line-item editors pull from so operators stop
retyping the same prices. Catalog items are *templates*: copying one onto a
document snapshots its values, so later edits to the catalog never mutate
existing quotes or invoices.

Money is stored in major units via ``Numeric`` to match
:mod:`app.models.invoice` and :mod:`app.models.quote`.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace


# A catalog item is either billable labour/services or a physical product. The
# distinction drives nothing in the backend today; it is a grouping/label that
# the UI filters on, kept as a constrained enum so the set stays clean.
CATALOG_ITEM_KINDS = ("service", "product")

# Which service line an item belongs to, so attach-rate reporting can tell a roof
# job apart from gutters. Unlike ``CATALOG_ITEM_KINDS`` this is only the *suggested*
# set the UI offers: the column is a plain ``String``, never a DB enum, because
# workspaces run trades we did not enumerate (decks, fencing, holiday lighting)
# and must be able to type their own category without a migration.
DEFAULT_SERVICE_CATEGORIES = ("roof", "siding", "gutters", "windows", "trim", "other")


class CatalogItem(Base, WorkspaceScoped):
    """A reusable priced product or service in a workspace's price book."""

    __tablename__ = "catalog_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional operator-facing code (e.g. a SKU or service code). Not unique:
    # workspaces import messy data and duplicates must not block a save.
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)

    kind: Mapped[str] = mapped_column(
        Enum(*CATALOG_ITEM_KINDS, name="catalog_item_kind"),
        nullable=False,
        default="service",
        index=True,
    )

    # Default price (major units) copied onto a line item when picked.
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    # Whether this item is taxable; surfaced so the picker can default tax.
    taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Soft archive: inactive items are hidden from pickers but kept for history.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    # Service line this item belongs to (see ``DEFAULT_SERVICE_CATEGORIES``).
    # Free-form and nullable: existing rows stay uncategorized until an operator
    # classifies them, and reporting treats NULL as "unknown", not as a category.
    # Indexed because attach-rate reporting groups by it.
    service_category: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    # Whether this item is an add-on sold alongside a primary job (a gutter guard
    # attached to a roof) rather than a standalone job. Drives attach-rate
    # numerator selection; defaults false so existing items keep counting as primary.
    is_attachable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # The ``service_category`` values this item can be attached to — e.g. ``["roof"]``
    # on a gutter add-on. Stored inline as a text array (not a join table) because
    # it is a short label list matched against a free-form category, not a
    # relationship. Empty list means "no restriction recorded".
    attach_targets: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )

    # Free-form attributes a fixture/service carries beyond price. Drives config
    # behaviour without new columns — e.g. ``{"transformer": true}`` excludes a
    # fixture from the Care Plan count, ``{"per_linear_foot": true}`` marks a
    # string-lighting rate. Nullable JSONB so existing rows are untouched.
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # SKU bill-of-materials for the internal fulfillment sheet: a list of
    # ``{"sku", "description", "qty"}`` parts that make up one unit of this item.
    # Purely internal; never rendered on the client proposal. Nullable JSONB.
    components: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self) -> str:
        return f"<CatalogItem(id={self.id}, name={self.name}, unit_price={self.unit_price})>"
