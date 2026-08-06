"""Every off-session charge attempt against a saved card — succeeded or not.

Two reasons this table exists rather than "just ask Stripe":

1. **A silent decline is invisible.** When a customer taps Pay and it fails, they
   see it. When a worker charges a card on file at 3am and it fails, nobody sees
   anything unless the failure is written down and someone is told.
2. **"Did we already try this?" must be answerable locally.** ``idempotency_key``
   is unique, so a retried worker tick, a double-clicked button, and a replayed
   webhook all collapse onto one attempt — and onto one PaymentIntent, because
   the same key is handed to Stripe.

``status`` distinguishes three outcomes that are routinely and expensively
conflated: ``succeeded``, ``requires_action`` (the customer must authenticate —
recoverable, not a loss), and ``declined`` (a hard no; do **not** retry on a
timer, that is how you earn card-network penalties).
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.contact_payment_method import ContactPaymentMethod
    from app.models.invoice import Invoice
    from app.models.workspace import Workspace


CHARGE_ATTEMPT_STATUSES = ("succeeded", "declined", "requires_action", "error")

CHARGE_STATUS_SUCCEEDED = "succeeded"
CHARGE_STATUS_DECLINED = "declined"
CHARGE_STATUS_REQUIRES_ACTION = "requires_action"
CHARGE_STATUS_ERROR = "error"

# What asked for this charge. Policy differs per trigger (three of the four
# automated ones default off per workspace), and a chargeback dispute starts with
# "why did you charge me?" — which this answers.
CHARGE_TRIGGERS = ("invoice", "deposit", "recurring_job", "no_show_fee", "manual")


class CardChargeAttempt(Base):
    """One attempt to charge a saved card while the customer was not present."""

    __tablename__ = "card_charge_attempts"
    __table_args__ = (
        Index("ix_card_charge_attempts_workspace_created", "workspace_id", "created_at"),
        Index("ix_card_charge_attempts_contact_created", "contact_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # ``SET NULL`` rather than cascade: removing a card must not erase the record
    # of money already taken with it.
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contact_payment_methods.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Null when Stripe never got far enough to mint one (network error before the
    # request landed); the webhook reconciler fills it in if the charge did happen.
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )

    # Major units, matching ``invoices.total`` — minor-unit conversion happens at
    # the Stripe boundary, not in storage.
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # Stripe's machine-readable reason (``insufficient_funds``, ``do_not_honor``…).
    # Kept distinct from ``failure_message`` because the code drives what we do and
    # the message is only ever shown to a human.
    decline_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Unique: the same key is sent to Stripe as its idempotency key, so one key
    # means one PaymentIntent *and* one row here.
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    contact: Mapped["Contact"] = relationship("Contact")
    payment_method: Mapped["ContactPaymentMethod | None"] = relationship("ContactPaymentMethod")
    invoice: Mapped["Invoice | None"] = relationship("Invoice")

    def __repr__(self) -> str:
        return (
            f"<CardChargeAttempt(id={self.id}, status={self.status}, "
            f"amount={self.amount} {self.currency}, trigger={self.trigger})>"
        )
