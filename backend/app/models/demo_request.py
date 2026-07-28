"""Demo request model for rate limiting."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String, Text, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString, LookupHash, hash_phone
from app.db.base import Base


class DemoRequest(Base):
    """Track demo requests for rate limiting."""

    __tablename__ = "demo_requests"
    __table_args__ = (
        # The per-phone rate-limit window scans by hash, not by the encrypted
        # column, so the composite index has to sit on ``phone_hash``.
        Index(
            "ix_demo_requests_phone_created_at",
            "phone_hash",
            "created_at",
        ),
        Index(
            "ix_demo_requests_client_ip_created_at",
            "client_ip",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # PII at rest — ``phone_number`` is Fernet-encrypted via :class:`EncryptedString`;
    # ``phone_hash`` carries the deterministic hash + index used for rate-limit
    # lookups. Kept in sync by the ``before_insert``/``before_update`` hook below.
    phone_number: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    phone_hash: Mapped[str] = mapped_column(LookupHash(), nullable=False, index=True)
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "call" or "text"
    client_ip: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending, initiated, failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        # ``phone_hash`` is only populated by the hook below at flush time, so
        # guard against the transient state rather than raising from __repr__.
        phone_hash = self.phone_hash
        fragment = f"{phone_hash[:8]}..." if phone_hash else None
        return (
            f"<DemoRequest(id={self.id}, phone_hash={fragment}, "
            f"type={self.request_type}, status={self.status})>"
        )


def _sync_demo_request_lookup_hashes(
    _mapper: object, _connection: object, target: DemoRequest
) -> None:
    """Keep the encrypted demo-request lookup hash in sync for all write paths."""
    if target.phone_number:
        target.phone_hash = hash_phone(target.phone_number)


event.listen(DemoRequest, "before_insert", _sync_demo_request_lookup_hashes)
event.listen(DemoRequest, "before_update", _sync_demo_request_lookup_hashes)
