"""Lead Source model for public lead ingestion."""

import secrets
import string
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def generate_lead_source_key() -> str:
    """Generate a short public key for lead source (e.g., ls_xK9mN2pQ)."""
    chars = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(8))
    return f"ls_{random_part}"


if TYPE_CHECKING:
    from app.models.workspace import Workspace


class LeadSource(Base):
    """Configurable lead source for public lead ingestion."""

    __tablename__ = "lead_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Basic info
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    public_key: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True, default=generate_lead_source_key
    )
    allowed_domains: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Post-capture action
    action: Mapped[str] = mapped_column(
        String(50), nullable=False, default="collect"
    )  # collect | auto_text | auto_call | enroll_campaign
    action_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")

    def __repr__(self) -> str:
        return f"<LeadSource(id={self.id}, name={self.name}, action={self.action})>"
