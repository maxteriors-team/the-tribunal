"""Outbound sequence models.

A reusable, workspace-scoped sequence template plus the per-prospect enrollment
and per-step attempt records that drive outbound execution. Sequences are
multi-channel (SMS, email, voice, manual) and intentionally decoupled from
:class:`~app.models.outbound_mission.OutboundMission` so a single sequence can
be reused across missions.
"""

import uuid
from datetime import UTC, datetime, time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.conversation import Conversation, Message
    from app.models.lead_prospect import LeadProspect
    from app.models.outbound_mission import OutboundMission
    from app.models.pending_action import PendingAction
    from app.models.workspace import Workspace


class OutboundSequenceStatus(StrEnum):
    """Outbound sequence lifecycle status."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class SequenceStepChannel(StrEnum):
    """Outbound sequence step delivery channel."""

    SMS = "sms"
    EMAIL = "email"
    VOICE = "voice"
    MANUAL = "manual"


class SequenceEnrollmentStatus(StrEnum):
    """Per-prospect sequence enrollment status."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    REPLIED = "replied"
    OPTED_OUT = "opted_out"
    CONVERTED = "converted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SequenceStepAttemptStatus(StrEnum):
    """Per-attempt status for a sequence step."""

    PENDING = "pending"
    SCHEDULED = "scheduled"
    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutboundSequence(Base):
    """Reusable multi-channel outbound sequence template."""

    __tablename__ = "outbound_sequences"
    __table_args__ = (
        Index(
            "ix_outbound_sequences_workspace_status",
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

    # Identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[OutboundSequenceStatus] = mapped_column(
        SAEnum(
            OutboundSequenceStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=OutboundSequenceStatus.DRAFT,
        index=True,
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Steps stored as JSONB array. Each step:
    # {
    #   "order": 0,
    #   "channel": "email" | "sms" | "voice" | "manual",
    #   "delay_hours": 0,
    #   "template": "...",
    #   "subject": "...",
    #   "agent_id": "<uuid>" | null,
    #   "stop_on_reply": true
    # }
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    # Fallback channel order when a step allows promotion (e.g. SMS → email).
    channel_priority: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    # Per-step retry cap
    max_attempts_per_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Sending windows
    sending_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    sending_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    sending_days: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York", nullable=False)

    # Denormalized stats
    total_enrollments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_replied: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_converted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
    enrollments: Mapped[list["OutboundSequenceEnrollment"]] = relationship(
        "OutboundSequenceEnrollment",
        back_populates="sequence",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<OutboundSequence(id={self.id}, name={self.name}, status={self.status})>"


class OutboundSequenceEnrollment(Base):
    """A single prospect's enrollment in an :class:`OutboundSequence`."""

    __tablename__ = "outbound_sequence_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "sequence_id",
            "prospect_id",
            name="uq_outbound_sequence_enrollments_sequence_prospect",
        ),
        Index(
            "ix_outbound_sequence_enrollments_status_next_step",
            "status",
            "next_step_at",
        ),
        Index(
            "ix_outbound_sequence_enrollments_mission_status",
            "mission_id",
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
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_sequences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prospect_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_prospects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Progress
    status: Mapped[SequenceEnrollmentStatus] = mapped_column(
        SAEnum(
            SequenceEnrollmentStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=SequenceEnrollmentStatus.ACTIVE,
        index=True,
    )
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_step_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Outcome tracking
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Stats
    attempts_made: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Lifecycle
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Standard timestamps
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
    mission: Mapped["OutboundMission | None"] = relationship(
        "OutboundMission", foreign_keys=[mission_id]
    )
    sequence: Mapped["OutboundSequence"] = relationship(
        "OutboundSequence", back_populates="enrollments"
    )
    prospect: Mapped["LeadProspect"] = relationship(
        "LeadProspect", back_populates="sequence_enrollments"
    )
    step_attempts: Mapped[list["OutboundSequenceStepAttempt"]] = relationship(
        "OutboundSequenceStepAttempt",
        back_populates="enrollment",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<OutboundSequenceEnrollment(id={self.id}, sequence={self.sequence_id}, "
            f"prospect={self.prospect_id}, step={self.current_step}, status={self.status})>"
        )


class OutboundSequenceStepAttempt(Base):
    """Per-step execution record for an :class:`OutboundSequenceEnrollment`."""

    __tablename__ = "outbound_sequence_step_attempts"
    __table_args__ = (
        UniqueConstraint(
            "enrollment_id",
            "step_index",
            "attempt_number",
            name="uq_outbound_step_attempts_enrollment_step_attempt",
        ),
        Index(
            "ix_outbound_step_attempts_enrollment_step",
            "enrollment_id",
            "step_index",
        ),
        Index(
            "ix_outbound_step_attempts_status_scheduled_at",
            "status",
            "scheduled_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_sequence_enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prospect_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_prospects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Step identity
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    channel: Mapped[SequenceStepChannel] = mapped_column(
        SAEnum(
            SequenceStepChannel,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    status: Mapped[SequenceStepAttemptStatus] = mapped_column(
        SAEnum(
            SequenceStepAttemptStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=SequenceStepAttemptStatus.PENDING,
        index=True,
    )

    # Timing
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # External refs (set if the step produced a real message/call/approval)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pending_actions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Outcome
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)
    outcome_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit snapshot — captures what we actually sent so later template edits
    # don't rewrite history.
    template_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Standard timestamps
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
    enrollment: Mapped["OutboundSequenceEnrollment"] = relationship(
        "OutboundSequenceEnrollment", back_populates="step_attempts"
    )
    prospect: Mapped["LeadProspect"] = relationship(
        "LeadProspect", back_populates="sequence_step_attempts"
    )
    message: Mapped["Message | None"] = relationship("Message", foreign_keys=[message_id])
    conversation: Mapped["Conversation | None"] = relationship(
        "Conversation", foreign_keys=[conversation_id]
    )
    pending_action: Mapped["PendingAction | None"] = relationship(
        "PendingAction", foreign_keys=[pending_action_id]
    )

    def __repr__(self) -> str:
        return (
            f"<OutboundSequenceStepAttempt(id={self.id}, enrollment={self.enrollment_id}, "
            f"step={self.step_index}, attempt={self.attempt_number}, status={self.status})>"
        )
