"""Invoice models for customer billing.

A workspace-scoped invoice with line items, mirroring the structure of
:mod:`app.models.opportunity` (``Opportunity`` + ``OpportunityLineItem``). Money
is stored in major units via ``Numeric``; Stripe minor-unit conversion happens at
request time in the payments service. ``status`` is derived by the service from
``amount_paid`` and ``due_date`` rather than set directly by clients.
"""

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DATE,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.user import User
    from app.models.workspace import Workspace


# Lifecycle of an invoice. Derived by the service from amount_paid + due_date;
# not free-set by API clients.
INVOICE_STATUSES = ("draft", "sent", "paid", "partial", "void", "overdue")


class Invoice(Base):
    """A customer invoice issued by a workspace."""

    __tablename__ = "invoices"
    __table_args__ = (
        # Human invoice number is unique within a workspace, not globally.
        UniqueConstraint("workspace_id", "number", name="uq_invoices_workspace_number"),
        # One external record (e.g. a Jobber invoice) maps to at most one invoice
        # per workspace, so the historical/AR import upserts idempotently.
        # Natively issued invoices leave both columns null.
        Index(
            "uq_invoices_workspace_external",
            "workspace_id",
            "external_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Bill-to contact. ``contacts.id`` is a BigInteger (not UUID).
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Optional link to the deal this invoice bills for.
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Human-facing invoice number, unique per workspace (e.g. "INV-000123").
    number: Mapped[str] = mapped_column(String(50), nullable=False)

    # Money (major units). Totals are computed server-side from line items.
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    tax_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    amount_paid: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    status: Mapped[str] = mapped_column(
        Enum(*INVOICE_STATUSES, name="invoice_status"),
        nullable=False,
        default="draft",
        index=True,
    )

    # Dates / lifecycle timestamps.
    issue_date: Mapped[date | None] = mapped_column(DATE, nullable=True)
    due_date: Mapped[date | None] = mapped_column(DATE, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stripe reconciliation handles (looked up by the payment webhook).
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )

    # Provenance for invoices imported from an external system (e.g. Jobber).
    # Imported as historical/AR records only — never re-billed. Together they form
    # the idempotency key for the one-time import (see the partial-unique index).
    external_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

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

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    contact: Mapped["Contact | None"] = relationship("Contact")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])
    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceLineItem.created_at",
    )

    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, number={self.number}, total={self.total} {self.currency})>"


class InvoiceLineItem(Base):
    """A single billable line on an invoice."""

    __tablename__ = "invoice_line_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pricing (major units). ``total`` is computed server-side as
    # ``quantity * unit_price - discount``; never trusted from the client.
    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    discount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="line_items")

    def __repr__(self) -> str:
        return f"<InvoiceLineItem(id={self.id}, name={self.name}, total={self.total})>"
