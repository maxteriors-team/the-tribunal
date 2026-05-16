"""Workspace invitation model."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace


def generate_invitation_token() -> str:
    """Generate a secure invitation token."""
    return secrets.token_urlsafe(32)


def default_expires_at() -> datetime:
    """Default expiration time: 7 days from now."""
    return datetime.now(UTC) + timedelta(days=7)


class WorkspaceInvitation(Base):
    """Invitation to join a workspace."""

    __tablename__ = "workspace_invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="member"
    )  # owner, admin, member
    token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, default=generate_invitation_token
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending, accepted, expired, cancelled
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    invited_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=default_expires_at
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    invited_by: Mapped["User | None"] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<WorkspaceInvitation(id={self.id}, email={self.email}, "
            f"workspace_id={self.workspace_id}, status={self.status})>"
        )

    @property
    def is_expired(self) -> bool:
        """Check if the invitation has expired."""
        return datetime.now(UTC) > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check if the invitation is still valid."""
        return self.status == "pending" and not self.is_expired
