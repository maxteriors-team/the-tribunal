"""Roofline permanent-vs-temporary comparison model.

A workspace-scoped, token-keyed snapshot of a rep's roofline estimate so a
homeowner can open a public page and see the permanent-vs-seasonal savings. Only
the *inputs* the rep measured are persisted (linear feet, optional zones,
takedown/storage); the money is recomputed from the live workspace pricing config
on every public view, so a rate change is reflected and no stale totals are stored.

Linear feet is stored here for internal recompute **only** — it is deliberately
never serialized onto the public :class:`app.schemas.estimate.PublicComparison`
payload. Mirrors the public-token pattern of :class:`app.models.quote.Quote`.
"""

import secrets
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace


def generate_comparison_token() -> str:
    """Return an unguessable URL-safe token for a public comparison page.

    192 bits of entropy so the link can be shared without auth yet stays
    non-enumerable, matching :func:`app.models.quote.generate_quote_token`.
    """
    return secrets.token_urlsafe(24)


class RooflineComparison(Base):
    """A shareable permanent-vs-temporary lighting comparison for one roofline."""

    __tablename__ = "roofline_comparisons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Public client-page token (unguessable, indexed for O(1) lookup).
    public_token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, default=generate_comparison_token
    )

    # Measured selection (INTERNAL — never serialized to the public payload).
    feet: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    channels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    takedown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    storage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Optional presentation context shown to the client / used internally.
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self) -> str:
        return f"<RooflineComparison(id={self.id}, token={self.public_token}, feet={self.feet})>"
