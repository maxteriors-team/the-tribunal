"""Reusable HTML email templates authored per workspace.

An operator writes the *content* — subject, an intro, the facts to list, a call
to action — and the branded shell in :mod:`app.services.email_layout` renders
it. Templates therefore store **structured blocks**, not raw HTML.

That is the load-bearing decision here. Storing raw HTML would mean operator
input is emitted into a customer's inbox verbatim, which is an injection sink
with no safe escaping strategy, and would freeze every saved template against
today's markup so a brand change could never reach mail already authored.
Blocks keep the operator's words as data: escaped on render, restyled for free.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class EmailTemplate(Base):
    """A saved, brand-rendered email an automation or operator can send."""

    __tablename__ = "email_templates"
    __table_args__ = (
        # Templates are picked by name in the workflow builder, so two with the
        # same name in one workspace is an authoring mistake, not a feature.
        UniqueConstraint("workspace_id", "name", name="uq_email_template_workspace_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Subject and heading support the same {first_name}-style placeholders the
    # SMS/email actions already use.
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    heading: Mapped[str | None] = mapped_column(String(500), nullable=True)
    preheader: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Ordered content blocks: [{"type": "paragraph", "text": "..."}, ...].
    # Validated by app.schemas.email_template before it reaches this column.
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    # "transactional" | "marketing" — decides whether the rendered footer
    # carries an unsubscribe link, and whether opted-out contacts are skipped.
    # Defaults to marketing: the safe default for a miscategorised template is
    # "carries an opt-out", never the reverse.
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, default="marketing", server_default="marketing"
    )

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

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="email_templates")

    def __repr__(self) -> str:
        return f"<EmailTemplate(id={self.id}, name={self.name}, category={self.category})>"
