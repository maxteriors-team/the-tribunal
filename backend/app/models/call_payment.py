"""CallPayment model — in-call payment / deposit collection records.

When the AI voice agent runs the ``collect_payment`` tool, it does NOT read raw
card numbers over the AI channel. Instead it creates a Stripe Checkout Session
for the requested amount and texts the secure payment link to the caller. Each
attempt is persisted here, linked to the call's :class:`Message`, the
conversation, the contact, and (optionally) an opportunity/deal, so operators
can see deposit/payment intent + status against the lead and get notified when
a caller actually pays.

Status transitions:
    pending  -> paid       (Stripe ``checkout.session.completed`` webhook, or an
                            in-call ``check_payment_status`` poll)
    pending  -> expired    (Stripe session expired without payment)
    pending  -> cancelled  (operator/agent cancelled)
    pending  -> failed     (payment failed)
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.conversation import Message


class CallPaymentStatus(StrEnum):
    """Lifecycle status of an in-call payment / deposit collection."""

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class CallPayment(Base, WorkspaceScoped):
    """A payment / deposit collected (or attempted) during a voice call."""

    __tablename__ = "call_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The call's Message row (the voice call during which payment was requested).
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Amount in the smallest currency unit is derived at Stripe time; we store
    # the human/decimal amount here for display + reconciliation.
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="usd")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[CallPaymentStatus] = mapped_column(
        SAEnum(
            CallPaymentStatus,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=CallPaymentStatus.PENDING,
        index=True,
    )

    # Stripe references. The session id is how the webhook + status polls resolve
    # this row back to the Stripe object; never store card data here.
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_link_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The outbound SMS Message row that carried the link (for traceability).
    sms_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set once operators have been notified of a successful payment so the
    # webhook and the in-call status poll never double-notify.
    operators_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationship (read-only side; Message does not back-populate to avoid
    # touching the broad conversation model for this leaf table).
    message: Mapped["Message | None"] = relationship(
        "Message", foreign_keys=[message_id], viewonly=True
    )

    def __repr__(self) -> str:
        return (
            f"<CallPayment(id={self.id}, amount={self.amount} {self.currency}, "
            f"status={self.status})>"
        )
