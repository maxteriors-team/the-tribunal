"""API Key model for CLI/agent authentication."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class APIKey(Base):
    """Long-lived API key for workspace-scoped CLI/agent access.

    A key is bound to exactly one workspace via ``workspace_id``. The auth layer
    (``app.api.deps._user_from_api_key`` /
    ``app.api.deps._enforce_api_key_workspace``) enforces this at request time:
    presenting a key issued for workspace A while calling a workspace-B endpoint
    yields HTTP 403, even if the underlying user is a member of B.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    workspace = relationship("Workspace")
    user = relationship("User")

    def __repr__(self) -> str:
        return f"<APIKey(id={self.id}, name={self.name}, prefix={self.key_prefix})>"
