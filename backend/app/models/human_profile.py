"""HumanProfile model for the HITL (Human-in-the-Loop) system."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.workspace import Workspace


class HumanProfile(Base):
    """Human profile for HITL action approval.

    Stores preferences and policies for a human operator
    linked to an AI agent, controlling when actions require
    human approval vs. auto-execution.
    """

    __tablename__ = "human_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Profile info
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(100), default="America/New_York", nullable=False
    )
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Preferences and policies
    communication_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    action_policies: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    default_policy: Mapped[str] = mapped_column(
        String(20), default="ask", nullable=False
    )
    auto_approve_timeout_minutes: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    auto_reject_timeout_minutes: Mapped[int] = mapped_column(
        Integer, default=1440, nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

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
    workspace: Mapped["Workspace"] = relationship("Workspace")
    agent: Mapped["Agent"] = relationship("Agent")

    def __repr__(self) -> str:
        return f"<HumanProfile(id={self.id}, display_name={self.display_name})>"
