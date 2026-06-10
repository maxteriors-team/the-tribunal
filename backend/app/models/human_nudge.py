"""HumanNudge model for relationship-building reminders to human operators."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.user import User
    from app.models.workspace import Workspace


class HumanNudge(Base):
    """Nudge/reminder sent to a human operator about a contact relationship."""

    __tablename__ = "human_nudges"
    __table_args__ = (
        Index(
            "ix_human_nudges_status_due_date",
            "status",
            "due_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable: workspace-level operator nudges (e.g. outbound batch ready,
    # approvals waiting) are not tied to a single contact.
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Nudge content
    nudge_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # birthday | anniversary | custom | cooling | follow_up | deal_milestone
    # noshow_recovery | unresponsive | hot_lead | referral_ask
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # send_card, call, text, email
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium"
    )  # low, medium, high

    # Scheduling
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source_date_field: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # e.g. "birthday", "anniversary"

    # Status workflow
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )  # pending, sent, acted, dismissed, snoozed
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Delivery tracking
    delivered_via: Mapped[str | None] = mapped_column(String(20), nullable=True)  # sms, push, both
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Assignment (nullable = all workspace members)
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Deduplication key: prevents duplicate nudges for the same event
    dedup_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    contact: Mapped["Contact | None"] = relationship("Contact")
    assigned_to: Mapped["User | None"] = relationship("User")
