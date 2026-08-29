"""Immutable invoice payment ledger for card, cash, and check receipts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base
from app.db.tenancy import WorkspaceScoped
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.invoice import Invoice
    from app.models.user import User
    from app.models.workspace import Workspace


class InvoicePayment(TimestampMixin, Base, WorkspaceScoped):
    """One append-only payment applied to an invoice."""

    __tablename__ = "invoice_payments"
    __table_args__ = (
        CheckConstraint(
            "payment_method IN ('card', 'cash', 'check', 'other')",
            name="ck_invoice_payments_method",
        ),
        CheckConstraint("amount > 0", name="ck_invoice_payments_amount_positive"),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_invoice_payments_workspace_idempotency",
        ),
        UniqueConstraint("external_event_id", name="uq_invoice_payments_external_event"),
        Index("ix_invoice_payments_workspace_invoice", "workspace_id", "invoice_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    reference: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    recorded_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    workspace: Mapped[Workspace] = relationship("Workspace")
    invoice: Mapped[Invoice] = relationship("Invoice", back_populates="payments")
    recorded_by: Mapped[User | None] = relationship("User")
