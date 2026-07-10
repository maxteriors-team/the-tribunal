"""Per-workspace calendar provider connection (Google Calendar OAuth).

Cal.com uses a single global API key; Google Calendar uses OAuth2 per workspace
(each workspace connects its own Google account). This table stores the
encrypted OAuth tokens plus the operational metadata the booking/sync code
needs: the target calendar, the push-notification watch channel, and the
incremental ``sync_token``.

Access/refresh tokens live inside the Fernet-encrypted ``credentials`` blob
(same scheme as :class:`app.models.workspace.WorkspaceIntegration`); everything
else is non-secret operational state queried directly by the refresh/renewal
workers. Never log the decrypted credentials.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import decrypt_json, encrypt_json
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class CalendarConnection(Base):
    """A workspace's connection to an external calendar provider (Google)."""

    __tablename__ = "calendar_connections"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "provider", name="uq_calendar_connection_workspace_provider"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Provider key ("google" today). Kept explicit so a second provider could be
    # added without another table.
    provider: Mapped[str] = mapped_column(
        String(50), default="google", server_default="google", nullable=False
    )

    # Fernet-encrypted JSON: {"access_token", "refresh_token"}.
    encrypted_credentials: Mapped[str] = mapped_column("credentials", Text, nullable=False)

    # Non-secret operational state.
    google_calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # events.watch push channel state (renewed by a worker; expires <= 7 days).
    watch_channel_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    watch_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    watch_expiration: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Incremental sync cursor for events.list(syncToken).
    sync_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
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

    # One-directional relationship (Workspace need not know about connections).
    workspace: Mapped["Workspace"] = relationship("Workspace")

    @property
    def credentials(self) -> dict[str, Any]:
        """Decrypt and return the OAuth credentials dict."""
        return decrypt_json(self.encrypted_credentials)

    @credentials.setter
    def credentials(self, value: dict[str, Any]) -> None:
        """Encrypt and store the OAuth credentials dict."""
        self.encrypted_credentials = encrypt_json(value)

    def safe_credentials(self) -> dict[str, Any] | None:
        """Decrypt credentials, returning ``None`` instead of raising on failure.

        A corrupted blob or an encryption-key rotation makes :attr:`credentials`
        raise. Status/read paths use this so one unreadable row never 500s a
        settings page.
        """
        try:
            return self.credentials
        except Exception:
            return None

    def __repr__(self) -> str:
        return (
            f"<CalendarConnection(workspace_id={self.workspace_id}, "
            f"provider={self.provider}, active={self.is_active})>"
        )
