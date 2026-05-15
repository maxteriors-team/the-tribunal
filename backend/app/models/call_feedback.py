"""CallFeedback model for collecting user and automated feedback."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if True:  # TYPE_CHECKING equivalent to avoid circular imports
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from app.models.call_outcome import CallOutcome
        from app.models.conversation import Message
        from app.models.user import User


class FeedbackSource(StrEnum):
    """Source of the feedback."""

    USER = "user"  # Dashboard user feedback
    CONTACT = "contact"  # Feedback from the person called
    AUTO_QUALITY = "auto_quality"  # LLM-as-judge quality scoring
    AGENT_SELF_EVAL = "agent_self_eval"  # Agent's own assessment


class ThumbsRating(StrEnum):
    """Simple thumbs up/down rating."""

    UP = "up"
    DOWN = "down"


class CallFeedback(Base):
    """User and automated feedback for calls.

    Collects multiple forms of feedback:
    - User ratings (1-5 stars or thumbs)
    - Free-form text feedback
    - Automated quality scores from LLM-as-judge
    - Structured feedback signals
    """

    __tablename__ = "call_feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Link to the call
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Optional link to outcome record
    call_outcome_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("call_outcomes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Feedback source
    source: Mapped[FeedbackSource] = mapped_column(
        SAEnum(
            FeedbackSource,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        index=True,
    )

    # Who provided feedback (for user feedback)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Rating options
    rating: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 1-5 star rating
    thumbs: Mapped[ThumbsRating | None] = mapped_column(
        SAEnum(
            ThumbsRating,
            native_enum=False,
            create_constraint=False,
            length=10,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )

    # Free-form feedback
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Structured feedback signals (JSON)
    # Example: {"tone_appropriate": true, "resolved_query": false, "followed_script": true}
    feedback_signals: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)

    # LLM quality assessment (for auto_quality source)
    quality_score: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 0.0-1.0
    quality_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    message: Mapped["Message"] = relationship("Message", back_populates="feedback")
    call_outcome: Mapped["CallOutcome | None"] = relationship("CallOutcome")
    user: Mapped["User | None"] = relationship("User")

    def __repr__(self) -> str:
        return f"<CallFeedback(id={self.id}, message_id={self.message_id}, source={self.source})>"
