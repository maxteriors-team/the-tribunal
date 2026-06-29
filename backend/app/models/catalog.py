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
from typing import TYPE_CHECKING

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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace


# A catalog item is either billable labour/services or a physical product. The
# distinction drives nothing in the backend today; it is a grouping/label that
# the UI filters on, kept as a constrained enum so the set stays clean.
CATALOG_ITEM_KINDS = ("service", "product")


class CatalogItem(Base):
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
