"""Review-request model for the reputation engine.

A ``ReviewRequest`` is the outbound "how did we do?" ask sent to a contact after
a completed appointment/job. It carries a unique public ``token`` that powers a
no-auth landing page where the recipient picks a star rating. High ratings are
routed to the workspace's public Google/Facebook review URL; low ratings are
routed to a private feedback form (the negative-feedback firewall) which creates
an internal :class:`app.models.review.Review` instead of a public one.
"""

import secrets
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.contact import Contact
    from app.models.review import Review
    from app.models.workspace import Workspace


def generate_review_token() -> str:
    """Return a URL-safe token for a public review-request landing page."""
    return secrets.token_urlsafe(24)


class ReviewRequestStatus(StrEnum):
    """Lifecycle of a review request."""

    PENDING = "pending"  # created, not yet sent
    SENT = "sent"  # SMS dispatched
    CLICKED = "clicked"  # recipient opened the landing page
    RATED = "rated"  # recipient picked a star rating
    COMPLETED = "completed"  # routed to public review or private feedback captured
    FAILED = "failed"  # send failed (no phone, opted out, provider error)


class ReviewRequestChannel(StrEnum):
    """Delivery channel for a review request."""

    SMS = "sms"


class ReviewRequest(Base, WorkspaceScoped):
    """An outbound review-request ask tied to a completed appointment/contact."""

    __tablename__ = "review_requests"
    __table_args__ = (
        Index(
            "ix_review_requests_workspace_status",
            "workspace_id",
            "status",
        ),
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
    appointment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Public landing-page token (unguessable, indexed for O(1) lookup).
    token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, default=generate_review_token
    )

    channel: Mapped[ReviewRequestChannel] = mapped_column(
        SAEnum(
            ReviewRequestChannel,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ReviewRequestChannel.SMS,
    )
    status: Mapped[ReviewRequestStatus] = mapped_column(
        SAEnum(
            ReviewRequestStatus,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ReviewRequestStatus.PENDING,
        index=True,
    )

    # Rating chosen by the recipient (1-5), null until they rate.
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Outbound tracking links.
    short_link_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("short_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    contact: Mapped["Contact"] = relationship("Contact")
    appointment: Mapped["Appointment | None"] = relationship("Appointment")
    review: Mapped["Review | None"] = relationship(
        "Review", back_populates="review_request", uselist=False
    )

    def __repr__(self) -> str:
        return (
            f"<ReviewRequest(id={self.id}, status={self.status}, "
            f"rating={self.rating}, contact_id={self.contact_id})>"
        )
