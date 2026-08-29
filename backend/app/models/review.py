"""Review model for the online reputation engine.

A ``Review`` captures customer sentiment collected through the reputation
engine. Two flavours exist, distinguished by :attr:`Review.is_public`:

* **Private feedback** — created when a recipient gives a low star rating and is
  routed to the private feedback form (the negative-feedback firewall). It never
  appears on a public site; operators triage it internally.
* **Public review intent** — created when a recipient gives a high star rating
  and is forwarded to the workspace's public Google/Facebook review URL.

Operators triage reviews, draft AI on-brand replies, and the aggregate of these
rows powers the per-workspace reputation score.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
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
    from app.models.contact import Contact
    from app.models.review_request import ReviewRequest
    from app.models.workspace import Workspace


class ReviewSource(StrEnum):
    """Where a review originated."""

    SMS_REQUEST = "sms_request"  # collected via a review-request SMS landing page
    GOOGLE = "google"
    FACEBOOK = "facebook"
    MANUAL = "manual"  # entered by an operator


class ReviewSentiment(StrEnum):
    """Coarse sentiment bucket derived from the rating."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class ReviewStatus(StrEnum):
    """Operator-facing triage state of a review."""

    NEW = "new"
    REPLIED = "replied"
    RESOLVED = "resolved"  # private feedback actioned/closed
    DISMISSED = "dismissed"


class Review(Base, WorkspaceScoped):
    """A collected review or private feedback item for a workspace."""

    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_reviews_workspace_status", "workspace_id", "status"),
        Index("ix_reviews_workspace_public", "workspace_id", "is_public"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    review_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_requests.id", ondelete="SET NULL"),
        nullable=True,
    )

    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    source: Mapped[ReviewSource] = mapped_column(
        SAEnum(
            ReviewSource,
            native_enum=False,
            create_constraint=False,
            length=30,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ReviewSource.SMS_REQUEST,
    )
    sentiment: Mapped[ReviewSentiment] = mapped_column(
        SAEnum(
            ReviewSentiment,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ReviewSentiment.NEUTRAL,
        index=True,
    )
    status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(
            ReviewStatus,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ReviewStatus.NEW,
        index=True,
    )

    # True => high rating routed to a public review site (positive testimonial).
    # False => low rating captured privately (negative-feedback firewall).
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Operator/AI reply drafting.
    reply_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    review_request: Mapped["ReviewRequest | None"] = relationship(
        "ReviewRequest", back_populates="review"
    )

    def __repr__(self) -> str:
        return (
            f"<Review(id={self.id}, rating={self.rating}, "
            f"sentiment={self.sentiment}, is_public={self.is_public})>"
        )
