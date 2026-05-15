"""PromptVersionStats model for daily aggregated metrics."""

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.prompt_version import PromptVersion


class PromptVersionStats(Base):
    """Daily aggregated metrics for prompt version performance.

    Stores pre-computed daily statistics for efficient dashboard queries
    and trend analysis. Updated by background workers.
    """

    __tablename__ = "prompt_version_stats"
    __table_args__ = (
        UniqueConstraint(
            "prompt_version_id", "stat_date", name="uq_prompt_version_stats_date"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Date of aggregation
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Call volume metrics
    total_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Outcome metrics
    appointments_booked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    leads_qualified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    no_answer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    voicemail_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Duration metrics
    avg_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Quality metrics
    avg_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    positive_feedback_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Computed rates (stored for efficient querying)
    booking_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    qualification_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    completion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationship
    prompt_version: Mapped["PromptVersion"] = relationship("PromptVersion")

    def __repr__(self) -> str:
        return f"<PromptVersionStats(version_id={self.prompt_version_id}, date={self.stat_date})>"
