"""Global opt-out model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class GlobalOptOut(Base):
    """Global opt-out list for phone numbers across all campaigns in a workspace."""

    __tablename__ = "global_opt_outs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "phone_number", name="uq_workspace_opt_out"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Opt-out details
    opted_out_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    opt_out_keyword: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # STOP, UNSUBSCRIBE, etc.
    source_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")

    def __repr__(self) -> str:
        return f"<GlobalOptOut(workspace_id={self.workspace_id}, phone_number={self.phone_number})>"
