"""Message test models for A/B testing outreach messages."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.campaign import Campaign
    from app.models.contact import Contact
    from app.models.conversation import Conversation
    from app.models.workspace import Workspace


class MessageTestStatus(StrEnum):
    """Message test status."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class TestContactStatus(StrEnum):
    """Contact status within a message test."""

    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    REPLIED = "replied"
    QUALIFIED = "qualified"
    OPTED_OUT = "opted_out"
    FAILED = "failed"


class MessageTest(Base):
    """Message test for A/B testing different outreach messages."""

    __tablename__ = "message_tests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
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

    # Test details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[MessageTestStatus] = mapped_column(
        SAEnum(
            MessageTestStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=MessageTestStatus.DRAFT,
        index=True,
    )

    # Phone settings
    from_phone_number: Mapped[str] = mapped_column(String(50), nullable=False)
    use_number_pool: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # AI settings
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    qualification_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Scheduling
    sending_hours_start: Mapped[datetime | None] = mapped_column(Time, nullable=True)
    sending_hours_end: Mapped[datetime | None] = mapped_column(Time, nullable=True)
    sending_days: Mapped[list[int] | None] = mapped_column(
        ARRAY(Integer), nullable=True
    )  # 0=Mon, 6=Sun
    timezone: Mapped[str] = mapped_column(
        String(50), default="America/New_York", nullable=False
    )

    # Rate limiting
    messages_per_minute: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    # Statistics (denormalized)
    total_contacts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_variants: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    replies_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contacts_qualified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Winner tracking
    winning_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_variants.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        index=True,
    )
    converted_to_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Error tracking
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="message_tests")
    agent: Mapped["Agent | None"] = relationship("Agent", back_populates="message_tests")
    winning_variant: Mapped["TestVariant | None"] = relationship(
        "TestVariant",
        foreign_keys=[winning_variant_id],
        post_update=True,
    )
    converted_to_campaign: Mapped["Campaign | None"] = relationship("Campaign")
    variants: Mapped[list["TestVariant"]] = relationship(
        "TestVariant",
        back_populates="message_test",
        cascade="all, delete-orphan",
        foreign_keys="TestVariant.message_test_id",
    )
    test_contacts: Mapped[list["TestContact"]] = relationship(
        "TestContact", back_populates="message_test", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<MessageTest(id={self.id}, name={self.name}, status={self.status})>"


class TestVariant(Base):
    """Individual message variant within a test."""

    __tablename__ = "test_variants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_test_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("message_tests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Variant details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    message_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_control: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Statistics (denormalized for quick analytics)
    contacts_assigned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    replies_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contacts_qualified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Computed rates (updated on stat changes)
    response_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    qualification_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

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
    message_test: Mapped["MessageTest"] = relationship(
        "MessageTest",
        back_populates="variants",
        foreign_keys=[message_test_id],
    )
    test_contacts: Mapped[list["TestContact"]] = relationship(
        "TestContact", back_populates="variant"
    )

    def update_rates(self) -> None:
        """Update computed response and qualification rates."""
        if self.messages_sent > 0:
            self.response_rate = (self.replies_received / self.messages_sent) * 100
        else:
            self.response_rate = 0.0

        if self.replies_received > 0:
            self.qualification_rate = (self.contacts_qualified / self.replies_received) * 100
        else:
            self.qualification_rate = 0.0

    def __repr__(self) -> str:
        return f"<TestVariant(id={self.id}, name={self.name}, is_control={self.is_control})>"


class TestContact(Base):
    """Contact enrollment in a message test."""

    __tablename__ = "test_contacts"
    __table_args__ = (
        UniqueConstraint("message_test_id", "contact_id", name="uq_test_contact"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_test_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("message_tests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_variants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Status tracking
    status: Mapped[TestContactStatus] = mapped_column(
        SAEnum(
            TestContactStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=TestContactStatus.PENDING,
        index=True,
    )

    # Qualification
    is_qualified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    qualification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Opt-out
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opted_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    first_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_reply_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    variant_assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Error tracking
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    message_test: Mapped["MessageTest"] = relationship(
        "MessageTest", back_populates="test_contacts"
    )
    contact: Mapped["Contact"] = relationship("Contact", back_populates="test_contacts")
    variant: Mapped["TestVariant | None"] = relationship(
        "TestVariant", back_populates="test_contacts"
    )
    conversation: Mapped["Conversation | None"] = relationship(
        "Conversation", back_populates="test_contacts"
    )

    def __repr__(self) -> str:
        return (
            f"<TestContact(message_test_id={self.message_test_id}, "
            f"contact_id={self.contact_id}, status={self.status})>"
        )
