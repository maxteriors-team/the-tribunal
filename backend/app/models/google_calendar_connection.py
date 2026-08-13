"""Per-user Google Calendar OAuth connection.

Refresh and access tokens are encrypted at rest.  A connection belongs to one
login, not a workspace: the same rep can use their calendar in every workspace
where that login is a member without sharing credentials with another user.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class GoogleCalendarConnection(Base):
    """Google OAuth credentials and selected booking calendar for one user."""

    __tablename__ = "google_calendar_connections"
    __table_args__ = (UniqueConstraint("user_id", name="uq_google_calendar_connections_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    google_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    google_email: Mapped[str] = mapped_column(String(320), nullable=False)
    calendar_id: Mapped[str] = mapped_column(String(1024), default="primary", nullable=False)

    access_token: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    refresh_token: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    granted_scopes: Mapped[str] = mapped_column(String(2048), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped[User] = relationship("User", lazy="raise")
