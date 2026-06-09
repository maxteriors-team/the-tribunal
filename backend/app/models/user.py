"""User model."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString, LookupHash, hash_phone, hash_value
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workspace import WorkspaceMembership


class User(Base):
    """User account."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # PII at rest — ``email`` and ``phone_number`` are Fernet-encrypted. The
    # ``email_hash`` column carries both the unique constraint (formerly on
    # ``email``) and the lookup index. ``phone_hash`` is non-unique because
    # multiple users may share a number (admin + assistant).
    email: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    email_hash: Mapped[str] = mapped_column(LookupHash(), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(LookupHash(), nullable=True, index=True)
    timezone: Mapped[str] = mapped_column(String(100), default="America/New_York", nullable=False)
    # Optional profile image URL. Non-PII — stored as plain text since the
    # URL itself (Gravatar hash, uploaded asset URL) is not sensitive.
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Notification preferences
    notification_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notification_sms: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notification_push: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notification_push_calls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notification_push_messages: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notification_push_voicemail: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notification_push_appointments: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    # Per-type preferences for actionable-event notifications (push + email).
    notification_push_reviews: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    notification_push_deal_alerts: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    notification_push_missed_call_textback: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    notification_push_roleplay: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    notification_push_automations: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
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
    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email_hash={self.email_hash[:8]}...)>"


def _sync_user_lookup_hashes(_mapper: object, _connection: object, target: User) -> None:
    """Keep encrypted user lookup hashes in sync for all write paths."""
    target.email_hash = hash_value(target.email)
    target.phone_hash = hash_phone(target.phone_number) if target.phone_number else None


event.listen(User, "before_insert", _sync_user_lookup_hashes)
event.listen(User, "before_update", _sync_user_lookup_hashes)
