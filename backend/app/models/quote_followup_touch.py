"""Durable execution ledger for automated quote follow-up touches.

Shared by both quote sequences. ``sequence_key`` says which one wrote a row and
what ``offset_days`` is measured from, so the two never read each other's work as
their own.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

# ``offset_days`` is measured from ``Quote.sent_at`` for the first-14-days
# cadence and from the quote's issue date for long-range revival.
SEQUENCE_POST_ESTIMATE = "post_estimate"
SEQUENCE_UNSOLD_REVIVAL = "unsold_revival"


class QuoteFollowupTouch(Base, WorkspaceScoped):
    """One processed cadence offset for a quote, for one named sequence.

    The unique ``(quote_id, sequence_key, offset_days)`` key and channel-level
    provider idempotency keys make worker retries safe without coupling state to
    mutable workspace configuration.
    """

    __tablename__ = "quote_followup_touches"
    __table_args__ = (
        UniqueConstraint(
            "quote_id",
            "sequence_key",
            "offset_days",
            name="uq_quote_followup_touches_quote_sequence_offset",
        ),
        Index(
            "ix_quote_followup_touches_workspace_processed",
            "workspace_id",
            "processed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_key: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=SEQUENCE_POST_ESTIMATE,
        server_default=SEQUENCE_POST_ESTIMATE,
    )
    offset_days: Mapped[int] = mapped_column(Integer, nullable=False)
    configured_channel: Mapped[str] = mapped_column(String(20), nullable=False)
    delivered_channel: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("message_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    human_nudge_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("human_nudges.id", ondelete="SET NULL"),
        nullable=True,
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
