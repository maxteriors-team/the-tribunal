"""A customer's card kept on file, plus the consent that authorises using it.

**No column in this table can hold a card number.** The primary account number
(PAN) is typed by the customer into a Stripe-owned iframe and never reaches this
application; what is stored here is the opaque ``pm_...`` handle plus the display
metadata Stripe hands back (brand, last four, expiry) so an operator can tell one
saved card from another. ``tests/services/payments/test_card_on_file_save.py``
asserts that no persisted value contains a 13–19 digit run.

The ``mandate_*`` columns are the compliance payload, not decoration. Stripe
requires that before charging a customer while they are not present we obtain —
and **keep a record of** — their written agreement covering: that we may initiate
payments on their behalf, the anticipated timing and frequency, how the amount is
determined, and the cancellation policy. Those columns are written server-side
from the request that confirmed the SetupIntent (the observed IP and user agent,
the wording version they saw), never from a boolean the client asserts.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.workspace import Workspace


# Lifecycle of a saved card. ``removed`` is a soft delete: the card is detached at
# Stripe and unusable here, but the row survives because it is the evidence trail
# for charges already made against it.
PAYMENT_METHOD_STATUSES = ("active", "removed", "expired")

PAYMENT_METHOD_STATUS_ACTIVE = "active"
PAYMENT_METHOD_STATUS_REMOVED = "removed"
PAYMENT_METHOD_STATUS_EXPIRED = "expired"


class ContactPaymentMethod(Base):
    """A payment method a contact authorised us to keep and reuse."""

    __tablename__ = "contact_payment_methods"
    __table_args__ = (
        # At most one default card per contact. A partial unique index rather than
        # a plain one because non-default rows are unconstrained, and "which card
        # do we charge?" must never have two answers.
        Index(
            "uq_contact_payment_methods_default",
            "contact_id",
            unique=True,
            postgresql_where=text("is_default AND status = 'active'"),
        ),
        # The charge path lists a contact's usable cards; the workspace column is
        # in the index so a tenant-scoped list never scans another tenant's rows.
        Index(
            "ix_contact_payment_methods_workspace_contact",
            "workspace_id",
            "contact_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # ``contacts.id`` is a BigInteger, not a UUID.
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Stripe handles. ``stripe_payment_method_id`` is unique so replaying the
    # ``setup_intent.succeeded`` webhook cannot create a second row for one card.
    stripe_payment_method_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Denormalised from ``contacts.stripe_customer_id`` so the off-session charge
    # path has both handles without a join, and so a later customer-id change
    # cannot silently repoint an existing card at a different customer.
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Display metadata only — enough to say "Visa ending 4242, exp 12/2029" and
    # nothing more. Never a PAN, never a CVC.
    brand: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    exp_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exp_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PAYMENT_METHOD_STATUS_ACTIVE,
        server_default=PAYMENT_METHOD_STATUS_ACTIVE,
        index=True,
    )

    # The written agreement Stripe requires us to retain. ``mandate_text_version``
    # names the exact wording the customer accepted, so consent copy can change
    # later without retroactively rewriting what anyone actually agreed to.
    mandate_text_version: Mapped[str] = mapped_column(String(50), nullable=False)
    mandate_accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    # Server-observed, not client-declared: these are the record, so a client that
    # lies about them would be forging its own consent evidence.
    mandate_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    mandate_user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped["Workspace"] = relationship("Workspace")
    contact: Mapped["Contact"] = relationship("Contact")

    @property
    def display_label(self) -> str:
        """Human label for the operator UI, e.g. ``"Visa •••• 4242"``."""
        brand = (self.brand or "Card").title()
        return f"{brand} •••• {self.last4}" if self.last4 else brand

    def __repr__(self) -> str:
        return (
            f"<ContactPaymentMethod(id={self.id}, contact_id={self.contact_id}, "
            f"{self.display_label}, status={self.status})>"
        )
