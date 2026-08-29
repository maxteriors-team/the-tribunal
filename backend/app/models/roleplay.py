"""Practice-arena roleplay models.

These power the user-facing "practice arena" where an operator rehearses a
configured AI agent (or a human rep) against synthetic prospect personas
*before* the agent talks to real leads. This is intentionally distinct from the
internal IVR-menu navigation harness in ``app.services.ai.testing`` — here an
LLM role-plays a believable prospect (skeptical homeowner, price-shopping
patient, budget-conscious solar lead) and the rehearsal is scored.

Two tables:

- ``ProspectPersona``: a reusable synthetic prospect. ``workspace_id IS NULL``
  marks a built-in template available to every workspace; a non-null
  ``workspace_id`` is a workspace-owned custom persona.
- ``RehearsalRun``: one scored rehearsal (transcript + report).
"""

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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.workspace import Workspace


class PersonaDifficulty(StrEnum):
    """How hard a synthetic prospect is to win over."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class RehearseeType(StrEnum):
    """Who is being rehearsed against the synthetic prospect."""

    AI = "ai"
    HUMAN = "human"


class RehearsalStatus(StrEnum):
    """Lifecycle of a rehearsal run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _difficulty_enum() -> SAEnum:
    return SAEnum(
        PersonaDifficulty,
        native_enum=False,
        create_constraint=False,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )


class ProspectPersona(Base, WorkspaceScoped):
    """A synthetic prospect an agent can rehearse against."""

    __tablename__ = "prospect_personas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NULL workspace_id => built-in template shared across all workspaces.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[PersonaDifficulty] = mapped_column(
        _difficulty_enum(), nullable=False, default=PersonaDifficulty.MEDIUM
    )
    # Default channel this persona is tuned for (sms or voice).
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="sms")

    # System prompt that makes the LLM act as this prospect.
    persona_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # The opening line the prospect sends to kick off the conversation.
    opening_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Objections the prospect should raise; used to score objection coverage.
    objections: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    # What the prospect ultimately wants (used to judge a successful close).
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    workspace: Mapped["Workspace | None"] = relationship("Workspace")
    runs: Mapped[list["RehearsalRun"]] = relationship(
        "RehearsalRun", back_populates="persona", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<ProspectPersona(id={self.id}, slug={self.slug}, builtin={self.is_builtin})>"


class RehearsalRun(Base, WorkspaceScoped):
    """One scored rehearsal of an agent (or human rep) vs a synthetic prospect."""

    __tablename__ = "rehearsal_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    persona_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prospect_personas.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Snapshot of what was rehearsed (survives agent/persona edits or deletes).
    agent_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    persona_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    rehearsee: Mapped[RehearseeType] = mapped_column(
        SAEnum(
            RehearseeType,
            native_enum=False,
            create_constraint=False,
            length=10,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=RehearseeType.AI,
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="sms")
    max_turns: Mapped[int] = mapped_column(Integer, default=6, nullable=False)

    status: Mapped[RehearsalStatus] = mapped_column(
        SAEnum(
            RehearsalStatus,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=RehearsalStatus.PENDING,
        index=True,
    )

    # Ordered list of {"role": "prospect"|"agent", "content": str} entries.
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    # === Scored report (populated when status == completed) ===
    # Structured scores: objection_coverage, booking, tone, overall, sentiment.
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    objection_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    booking_attempted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tone_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    strengths: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    gaps: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    suggestions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped["Workspace"] = relationship("Workspace")
    agent: Mapped["Agent | None"] = relationship("Agent")
    persona: Mapped["ProspectPersona | None"] = relationship(
        "ProspectPersona", back_populates="runs"
    )

    def __repr__(self) -> str:
        return f"<RehearsalRun(id={self.id}, status={self.status}, score={self.overall_score})>"
