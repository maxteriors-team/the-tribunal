"""Quote (estimate) models.

A workspace-scoped quote with line items, mirroring :mod:`app.models.invoice`
(``Invoice`` + ``InvoiceLineItem``). Money is stored in major units via
``Numeric``; line and header totals are computed server-side from the line items.

A quote is the sales-side document that precedes a job and/or an invoice. Its
lifecycle is operator-driven (``draft -> sent -> approved/declined``), with
``expired`` derived once a sent quote passes ``expiry_date``. On approval an
operator can **convert** the quote into a scheduled :class:`Job` and/or an
:class:`Invoice`; the resulting ids are recorded on the quote so the
quote -> job -> invoice chain stays auditable.
"""

import secrets
import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DATE,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.field_service import ServiceLocation
    from app.models.user import User
    from app.models.workspace import Workspace


# Lifecycle of a quote. ``draft``/``sent`` are mutable; ``approved``/``declined``
# are terminal operator decisions; ``expired`` is derived from ``expiry_date`` on
# a still-``sent`` quote by the service (never free-set by API clients).
QUOTE_STATUSES = ("draft", "sent", "approved", "declined", "expired")


def generate_quote_token() -> str:
    """Return a URL-safe token for a public client proposal page.

    Unguessable (192 bits of entropy) so a proposal link can be shared without
    auth yet not be enumerable. Allocated lazily on first ``send`` — drafts have
    no token.
    """
    return secrets.token_urlsafe(24)


class Quote(Base):
    """A customer quote/estimate issued by a workspace."""

    __tablename__ = "quotes"
    __table_args__ = (
        # Human quote number is unique within a workspace, not globally.
        UniqueConstraint("workspace_id", "number", name="uq_quotes_workspace_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Quote-to contact. ``contacts.id`` is a BigInteger (not UUID).
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Optional job site this quote is for (becomes the converted job's location).
    service_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Optional link to the deal this quote belongs to.
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Human-facing quote number, unique per workspace (e.g. "QUO-000123").
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    # Short summary; also used as the title of the job a quote converts into.
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Money (major units). Totals are computed server-side from line items.
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    tax_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    # Optional upfront deposit the client can pay online to accept the quote.
    # Percentage of ``total`` (0-100); null = no deposit requested. The deposit
    # amount is derived (never stored) so it always tracks the live total.
    deposit_percentage: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Deposit payment provenance (Stripe Checkout in ``payment`` mode). Set once
    # the client pays; ``deposit_paid_at`` is the idempotency guard for the webhook.
    deposit_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deposit_checkout_session_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    deposit_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(
        Enum(*QUOTE_STATUSES, name="quote_status"),
        nullable=False,
        default="draft",
        index=True,
    )

    # Dates / lifecycle timestamps.
    issue_date: Mapped[date | None] = mapped_column(DATE, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(DATE, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Structured snapshot of the sales-wizard's collected state: selected tiers,
    # per-tier fixture lines, financing terms, cash pricing, Care Plan choice,
    # savings, and add-ons. The canonical ``line_items`` above stay the trusted,
    # server-computed totals for the accepted headline tier; this JSONB holds the
    # richer multi-tier presentation the public page renders. Nullable — a plain
    # quote created outside the wizard never sets it.
    proposal_document: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Public client-proposal token (unguessable, indexed for O(1) lookup). Null
    # until the quote is first sent; the public ``/p/quotes/{token}`` page and
    # its approve/decline actions are keyed on it. Drafts never resolve.
    public_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )

    # Conversion provenance — set when an approved quote is turned into a job
    # and/or an invoice, so the sales -> work -> billing chain is auditable.
    converted_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_service_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    converted_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

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
    service_location: Mapped["ServiceLocation | None"] = relationship("ServiceLocation")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])
    line_items: Mapped[list["QuoteLineItem"]] = relationship(
        "QuoteLineItem",
        back_populates="quote",
        cascade="all, delete-orphan",
        order_by="QuoteLineItem.created_at",
    )

    def __repr__(self) -> str:
        return f"<Quote(id={self.id}, number={self.number}, total={self.total} {self.currency})>"


class QuoteLineItem(Base):
    """A single line on a quote."""

    __tablename__ = "quote_line_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="CASCADE"),
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

    quote: Mapped["Quote"] = relationship("Quote", back_populates="line_items")

    def __repr__(self) -> str:
        return f"<QuoteLineItem(id={self.id}, name={self.name}, total={self.total})>"
