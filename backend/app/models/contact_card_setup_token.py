"""Short-lived, single-use links that let a customer save their own card.

The invoice and proposal share tokens are permanent on purpose — a customer may
bookmark their invoice and come back to it for weeks. This token is the opposite
and deliberately so: a permanent "enter your card here" URL is a standing
phishing asset. Anyone who ever sees the link — forwarded email, shoulder-surfed
screen, a text thread that outlives the relationship — could re-open a page that
looks exactly like the business's own card form.

So it expires (72 hours, long enough to survive a weekend) and burns on use.
``used_at`` is set the moment a SetupIntent is minted against it, which is also
what stops the unauthenticated endpoint from being an unbounded generator of
billable Stripe objects.

Entropy matches ``invoices.public_token``: ``secrets.token_urlsafe(24)``, 192
bits, not enumerable.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.workspace import Workspace


# Long enough that a link texted on Friday still works Monday morning; short
# enough that a leaked link is dead before it is useful.
CARD_SETUP_TOKEN_TTL_HOURS = 72


def generate_card_setup_token() -> str:
    """Return an unguessable URL-safe token for a card-setup link."""
    return secrets.token_urlsafe(24)


def default_card_setup_expiry() -> datetime:
    """Return the expiry timestamp for a token minted now."""
    return datetime.now(UTC) + timedelta(hours=CARD_SETUP_TOKEN_TTL_HOURS)


class ContactCardSetupToken(Base):
    """One customer's time-boxed invitation to put a card on file."""

    __tablename__ = "contact_card_setup_tokens"
    __table_args__ = (
        # The operator UI shows "link sent, expires in 2 days" per contact.
        Index("ix_contact_card_setup_tokens_contact_created", "contact_id", "created_at"),
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

    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=default_card_setup_expiry
    )
    # Set when a SetupIntent is minted against this token. Single-use: the link
    # dies at that point, whether or not the customer finished typing.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    contact: Mapped["Contact"] = relationship("Contact")

    @property
    def is_expired(self) -> bool:
        """Whether the link's 72-hour window has closed."""
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return datetime.now(UTC) >= expires

    @property
    def is_usable(self) -> bool:
        """Whether this token can still open a card form."""
        return self.used_at is None and not self.is_expired

    def __repr__(self) -> str:
        return (
            f"<ContactCardSetupToken(contact_id={self.contact_id}, "
            f"used={self.used_at is not None}, expires_at={self.expires_at})>"
        )
