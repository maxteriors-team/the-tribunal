"""CallOutcome model for structured call outcome tracking."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.conversation import Message
    from app.models.prompt_version import PromptVersion


class OutcomeType(StrEnum):
    """Call outcome types."""

    NO_ANSWER = "no_answer"
    BUSY = "busy"
    REJECTED = "rejected"
    VOICEMAIL = "voicemail"
    COMPLETED = "completed"
    APPOINTMENT_BOOKED = "appointment_booked"
    LEAD_QUALIFIED = "lead_qualified"
    FAILED = "failed"


class ClassifiedBy(StrEnum):
    """How the outcome was classified."""

    HANGUP_CAUSE = "hangup_cause"  # Classified from Telnyx hangup cause
    LLM_JUDGE = "llm_judge"  # Classified by LLM quality assessment
    USER = "user"  # Manually classified by user
    BOOKING_SIGNAL = "booking_signal"  # Inferred from booking attempt


class CallOutcome(Base):
    """Structured outcome tracking for calls with prompt attribution.

    Links each call's outcome to the specific prompt version used,
    enabling performance analysis and A/B testing.
    """

    __tablename__ = "call_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Link to the call (message record)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One outcome per call
        index=True,
    )

    # Attribution to prompt version
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Outcome classification
    outcome_type: Mapped[OutcomeType] = mapped_column(
        SAEnum(
            OutcomeType,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        index=True,
    )

    # Flexible outcome signals (JSON)
    # Example: {"appointment_booked": true, "lead_qualified": true, "duration_seconds": 180}
    # Transcript analysis keys (populated by transcript_analysis_worker):
    # - "sentiment": "positive" | "neutral" | "negative"
    # - "sentiment_score": float between -1.0 and 1.0
    # - "intents": list[str]
    # - "topics": list[str]
    # - "summary": str (1-2 sentence call summary)
    # - "objections": list[str]
    # - "next_steps": list[str]
    # - "analyzed": true when analysis succeeded, "error" when it failed
    signals: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)

    # Classification metadata
    classified_by: Mapped[ClassifiedBy] = mapped_column(
        SAEnum(
            ClassifiedBy,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ClassifiedBy.HANGUP_CAUSE,
    )
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Raw data for debugging
    raw_hangup_cause: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Decision-time context for bandit learning
    context: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=True)

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
    message: Mapped["Message"] = relationship("Message", back_populates="call_outcome")
    prompt_version: Mapped["PromptVersion | None"] = relationship("PromptVersion")

    def __repr__(self) -> str:
        return f"<CallOutcome(id={self.id}, outcome={self.outcome_type})>"
