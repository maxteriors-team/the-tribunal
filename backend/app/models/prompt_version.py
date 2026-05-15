"""PromptVersion model for tracking agent prompt snapshots."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User


class PromptVersion(Base):
    """Immutable snapshot of an agent's prompt configuration.

    Used for attribution - tracking which exact prompt was used for each call
    to enable A/B testing and performance analysis.
    """

    __tablename__ = "prompt_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Immutable prompt snapshot
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    initial_greeting: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)

    # Version tracking
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Who created this version
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Status flags
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Rollback tracking
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Denormalized counters (updated by workers)
    total_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    booked_appointments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Multi-armed bandit statistics (Beta distribution priors)
    bandit_alpha: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    bandit_beta: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    total_reward: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reward_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Multi-variant A/B testing fields
    traffic_percentage: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Fixed allocation (0-100), None = use bandit
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )  # Groups related variants
    arm_status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, index=True
    )  # active, paused, eliminated

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="prompt_versions")
    created_by: Mapped["User | None"] = relationship("User")
    parent_version: Mapped["PromptVersion | None"] = relationship(
        "PromptVersion", remote_side=[id], foreign_keys=[parent_version_id]
    )

    def __repr__(self) -> str:
        return f"<PromptVersion(id={self.id}, agent_id={self.agent_id}, v{self.version_number})>"
