"""Lead magnet model for offer bonuses and freebies."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.offer_lead_magnet import OfferLeadMagnet
    from app.models.workspace import Workspace


class LeadMagnetType(StrEnum):
    """Types of lead magnets."""

    PDF = "pdf"
    VIDEO = "video"
    CHECKLIST = "checklist"
    TEMPLATE = "template"
    WEBINAR = "webinar"
    FREE_TRIAL = "free_trial"
    CONSULTATION = "consultation"
    EBOOK = "ebook"
    MINI_COURSE = "mini_course"
    # Rich interactive types
    QUIZ = "quiz"
    CALCULATOR = "calculator"
    RICH_TEXT = "rich_text"
    VIDEO_COURSE = "video_course"


class DeliveryMethod(StrEnum):
    """How the lead magnet is delivered."""

    EMAIL = "email"
    DOWNLOAD = "download"
    REDIRECT = "redirect"
    SMS = "sms"


class LeadMagnet(Base):
    """Lead magnet/freebie that can be attached to offers as bonuses."""

    __tablename__ = "lead_magnets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Lead magnet details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Type and delivery
    magnet_type: Mapped[LeadMagnetType] = mapped_column(
        SAEnum(
            LeadMagnetType,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=LeadMagnetType.PDF,
    )
    delivery_method: Mapped[DeliveryMethod] = mapped_column(
        SAEnum(
            DeliveryMethod,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DeliveryMethod.EMAIL,
    )

    # Content
    content_url: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Rich content data (for quizzes, calculators, rich text, etc.)
    content_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Value perception (for Hormozi-style value stacking)
    estimated_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Status and tracking
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    download_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timestamps
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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="lead_magnets")
    offer_lead_magnets: Mapped[list["OfferLeadMagnet"]] = relationship(
        "OfferLeadMagnet", back_populates="lead_magnet", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<LeadMagnet(id={self.id}, name={self.name}, type={self.magnet_type})>"
