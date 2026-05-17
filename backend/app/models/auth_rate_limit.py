"""Auth rate limit model for tracking authentication attempts."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthRateLimit(Base):
    """Track authentication requests for IP- and username-based rate limiting.

    A single row represents one attempt at an auth endpoint. The IP-based limiter
    counts rows by ``client_ip``; the username-based lockout counts rows by
    ``username_hash`` to prevent distributed brute-force across many IPs against
    the same account. ``username_hash`` is only populated for the ``login_failed``
    endpoint (rows recorded on bad credentials) so successful logins do not
    consume a user's budget.
    """

    __tablename__ = "auth_rate_limits"
    __table_args__ = (
        Index(
            "ix_auth_rate_limits_client_ip_created_at",
            "client_ip",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_ip: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "login", "login_failed", "register", "refresh"
    # SHA-256 hex digest of the lowercased username, or NULL for non-username
    # endpoints. Hashed (not stored plaintext) so the table never enumerates
    # account identifiers on its own.
    username_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AuthRateLimit(id={self.id}, ip={self.client_ip}, endpoint={self.endpoint})>"
