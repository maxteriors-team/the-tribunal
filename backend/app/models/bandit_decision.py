"""BanditDecision model for tracking multi-armed bandit arm selections."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.conversation import Message
    from app.models.prompt_version import PromptVersion


class DecisionType(StrEnum):
    """How the arm was selected."""

    EXPLORE = "explore"
    EXPLOIT = "exploit"
    THOMPSON_SAMPLING = "thompson_sampling"
    UCB = "ucb"


class BanditDecision(Base):
    """Tracks which prompt version (arm) was selected for a call.

    Records the decision-time context and statistics to enable
    offline analysis and debugging of the bandit algorithm.
    """

    __tablename__ = "bandit_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Link to the agent
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The selected arm (prompt version)
    arm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Link to the call (message record) - unique per call
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )

    # How the arm was selected
    decision_type: Mapped[DecisionType] = mapped_column(
        SAEnum(
            DecisionType,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    # Exploration rate (epsilon) when using epsilon-greedy
    exploration_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Arm statistics at decision time
    # Example: {"alpha": 5.0, "beta": 3.0, "sampled_value": 0.625}
    arm_statistics: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    # Context snapshot at decision time
    # Example: {"time_of_day": "morning", "day_of_week": "monday", "lead_score_bucket": "high"}
    context_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    # Reward observation (filled after call outcome)
    observed_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    reward_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent")
    arm: Mapped["PromptVersion"] = relationship("PromptVersion")
    message: Mapped["Message | None"] = relationship("Message")

    def __repr__(self) -> str:
        return f"<BanditDecision(id={self.id}, type={self.decision_type})>"
