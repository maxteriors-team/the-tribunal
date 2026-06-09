"""AI Agent model."""

import secrets
import string
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants.text_response_timing import TEXT_RESPONSE_DEFAULT_DELAY_MS
from app.db.base import Base


def generate_public_id() -> str:
    """Generate a short public ID for embedding (e.g., ag_xK9mN2pQ)."""
    chars = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(8))
    return f"ag_{random_part}"


if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.bookable_staff import BookableStaff
    from app.models.campaign import Campaign
    from app.models.conversation import Conversation, Message
    from app.models.message_test import MessageTest
    from app.models.phone_number import PhoneNumber
    from app.models.prompt_version import PromptVersion
    from app.models.workspace import Workspace


class Agent(Base):
    """AI agent for voice and text conversations."""

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Basic info
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Channel configuration
    channel_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="both"
    )  # voice, text, both

    # Voice configuration
    voice_provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="openai"
    )  # openai, elevenlabs
    voice_id: Mapped[str] = mapped_column(
        String(100), nullable=False, default="alloy"
    )  # alloy, shimmer, nova, or ElevenLabs voice ID
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en-US")

    # OpenAI Realtime settings
    turn_detection_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="server_vad"
    )
    turn_detection_threshold: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    silence_duration_ms: Mapped[int] = mapped_column(Integer, default=500, nullable=False)

    # LLM settings
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2000, nullable=False)

    # Greeting
    initial_greeting: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Text agent settings
    text_response_delay_ms: Mapped[int] = mapped_column(
        Integer, default=TEXT_RESPONSE_DEFAULT_DELAY_MS, nullable=False
    )
    text_max_context_messages: Mapped[int] = mapped_column(Integer, default=20, nullable=False)

    # Cal.com integration
    calcom_event_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # How the booking tool picks which Cal.com event type / staff member to book.
    #   "single"       -> always use calcom_event_type_id (legacy default)
    #   "round_robin"  -> distribute across the agent's active bookable_staff pool
    #   "skill_based"  -> match the requested skill, then round-robin among matches
    assignment_strategy: Mapped[str] = mapped_column(
        String(20), default="single", server_default="single", nullable=False
    )

    # Tools enabled
    enabled_tools: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=lambda: ["book_appointment"], nullable=False
    )
    tool_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # IVR navigation settings
    enable_ivr_navigation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ivr_navigation_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    ivr_loop_threshold: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    # IVR timing configuration (milliseconds)
    ivr_silence_duration_ms: Mapped[int] = mapped_column(Integer, default=3000, nullable=False)
    ivr_post_dtmf_cooldown_ms: Mapped[int] = mapped_column(Integer, default=3000, nullable=False)
    ivr_menu_buffer_silence_ms: Mapped[int] = mapped_column(Integer, default=2000, nullable=False)

    # Call recording
    enable_recording: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Live human transfer / handoff (warm vs cold)
    # Destination phone number the AI hands an active call to when the caller
    # asks for a human or qualifies as hot. When NULL the transfer_call tool is
    # not exposed even if listed in enabled_tools (falls back to workspace
    # settings["transfer_destination_number"] if present).
    transfer_destination_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # "warm" speaks a short briefing to the human before bridging; "cold"
    # bridges immediately via the native Telnyx transfer command.
    transfer_mode: Mapped[str] = mapped_column(
        String(10), default="warm", server_default="warm", nullable=False
    )
    # Optional template for the spoken warm-transfer briefing. Supports
    # {caller_name}, {intent}, {summary}. Falls back to a generated sentence.
    transfer_briefing_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Appointment reminder settings
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reminder_minutes_before: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    # Multi-touch reminder offsets (minutes before appointment) and custom SMS body
    reminder_offsets: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=lambda: [1440, 120, 30], nullable=False
    )
    reminder_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Send re-engagement SMS with rebook link when a contact no-shows
    noshow_sms_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    # Custom no-show SMS template; supports {first_name} and {reschedule_link}
    noshow_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Post-meeting SMS (sent when a meeting is marked completed/attended)
    post_meeting_sms_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    post_meeting_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Value-reinforcement follow-up (sent X minutes after a completed meeting)
    value_reinforcement_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    value_reinforcement_offset_minutes: Mapped[int] = mapped_column(
        Integer, default=120, server_default="120", nullable=False
    )
    value_reinforcement_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Never-booked re-engagement (drip for contacts who never booked)
    never_booked_reengagement_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    never_booked_delay_days: Mapped[int] = mapped_column(
        Integer, default=7, server_default="7", nullable=False
    )
    never_booked_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    never_booked_max_attempts: Mapped[int] = mapped_column(
        Integer, default=2, server_default="2", nullable=False
    )

    # No-show multi-day re-engagement sequence
    noshow_reengagement_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    noshow_day3_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    noshow_day7_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Embed settings
    public_id: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, index=True
    )
    embed_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allowed_domains: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    embed_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Stats (denormalized)
    total_calls: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_messages: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Auto-improvement settings
    auto_suggest: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Generate suggestions automatically
    auto_activate: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Auto-approve and activate suggestions
    auto_improve_min_calls: Mapped[int] = mapped_column(
        Integer, default=100, nullable=False
    )  # Min calls before suggesting
    auto_evaluate: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Auto-declare winners and eliminate losers

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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="agents")
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="assigned_agent",
        foreign_keys="Conversation.assigned_agent_id",
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="agent", foreign_keys="Message.agent_id"
    )
    campaigns: Mapped[list["Campaign"]] = relationship(
        "Campaign", back_populates="agent", foreign_keys="Campaign.agent_id"
    )
    appointments: Mapped[list["Appointment"]] = relationship("Appointment", back_populates="agent")
    bookable_staff: Mapped[list["BookableStaff"]] = relationship(
        "BookableStaff", back_populates="agent", cascade="all, delete-orphan"
    )
    phone_numbers: Mapped[list["PhoneNumber"]] = relationship(
        "PhoneNumber", back_populates="assigned_agent"
    )
    message_tests: Mapped[list["MessageTest"]] = relationship("MessageTest", back_populates="agent")
    prompt_versions: Mapped[list["PromptVersion"]] = relationship(
        "PromptVersion",
        back_populates="agent",
        order_by="PromptVersion.version_number.desc()",
    )

    def __repr__(self) -> str:
        return f"<Agent(id={self.id}, name={self.name}, channel={self.channel_mode})>"
