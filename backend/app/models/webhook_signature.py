"""Durable ledger of provider webhook signatures we have already accepted.

Provider webhook signatures from HMAC-over-body schemes authenticate the
*payload*, not the *delivery*: the same ``(body, signature)`` pair stays
cryptographically valid forever. Anyone who
captures one — a proxy log, a mirrored request, a leaked APM trace — can resend
it verbatim and it will verify.

The only durable defense is remembering which signatures we have already
honoured. Redis alone is not sufficient for that: it is an availability-tier
dependency that we intentionally allow to fail, and a flush/eviction/outage
silently reopens the replay window. This table is the Postgres-backed
system of record.

Rows are pruned by :mod:`app.workers.webhook_signature_cleanup_worker` after
``SIGNATURE_RETENTION_DAYS`` so the table stays bounded. That retention window
is an explicit, documented tradeoff: a captured pair replayed *after* the window
would be accepted again, so the webhook secret should still be rotated if a
capture is ever suspected.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SeenWebhookSignature(Base):
    """One row per provider webhook signature that has been accepted once.

    The ``(provider, signature)`` UNIQUE constraint is the enforcement point:
    the claim path inserts with ``ON CONFLICT DO NOTHING`` and treats "no row
    inserted" as a replay. Uniqueness is scoped by ``provider`` so two
    integrations can never collide (or alias) on each other's digests.
    """

    __tablename__ = "seen_webhook_signatures"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "signature",
            name="uq_seen_webhook_signatures_provider_signature",
        ),
        # Supports the retention sweep's indexed range delete.
        Index("ix_seen_webhook_signatures_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Short provider slug (for example, "resend"). Kept separate from the digest so the
    # ledger can be shared by every signed-webhook integration.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)

    # The verbatim signature header value. The column is oversized so a provider
    # that switches to a longer
    # or prefixed encoding does not need a migration. Anything reaching this
    # column has already passed HMAC verification, so it is attacker-*chosen*
    # only in the sense that it equals a digest we computed ourselves.
    signature: Mapped[str] = mapped_column(String(128), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        # Never interpolate the digest itself — reprs land in logs.
        return f"<SeenWebhookSignature(id={self.id}, provider={self.provider})>"
