"""Transactional outbox rows for paid-invoice customer receipts."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

RECEIPT_PENDING = "pending"
RECEIPT_PROCESSING = "processing"
RECEIPT_SENT = "sent"
RECEIPT_TERMINAL = "terminal"


class InvoicePaymentReceiptOutbox(Base, WorkspaceScoped):
    """Immutable receipt snapshot plus bounded delivery state."""

    __tablename__ = "invoice_payment_receipt_outbox"
    __table_args__ = (
        UniqueConstraint(
            "invoice_id",
            "payment_event_id",
            name="uq_invoice_receipt_outbox_invoice_event",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'terminal')",
            name="status",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 0 AND 5",
            name="attempt_count",
        ),
        Index(
            "ix_invoice_receipt_outbox_due",
            "status",
            "next_attempt_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "workspaces.id",
            ondelete="CASCADE",
            name="fk_invoice_receipt_outbox_workspace",
        ),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "invoices.id",
            ondelete="CASCADE",
            name="fk_invoice_receipt_outbox_invoice",
        ),
        nullable=False,
    )
    payment_event_id: Mapped[str] = mapped_column(String(255), nullable=False)

    recipient_email: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    customer_name: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    service_summary: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    payment_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    invoice_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    balance_remaining: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_email: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    support_phone: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    invoice_url: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=RECEIPT_PENDING,
        server_default=RECEIPT_PENDING,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
