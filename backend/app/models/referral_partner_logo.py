"""Bounded raster logo bytes for referral-partner profiles."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

MAX_REFERRAL_PARTNER_LOGO_BYTES = 2 * 1024 * 1024
REFERRAL_PARTNER_LOGO_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp")


class ReferralPartnerLogo(Base, WorkspaceScoped):
    """One validated logo per partner; bytes stay outside scoreboard rows."""

    __tablename__ = "referral_partner_logos"
    __table_args__ = (
        ForeignKeyConstraint(
            ["referral_partner_id", "workspace_id"],
            ["referral_partners.id", "referral_partners.workspace_id"],
            name="fk_referral_partner_logos_scoped_partner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            f"size_bytes > 0 AND size_bytes <= {MAX_REFERRAL_PARTNER_LOGO_BYTES}",
            name="size_bytes",
        ),
        CheckConstraint(
            f"content_type IN {REFERRAL_PARTNER_LOGO_CONTENT_TYPES}",
            name="content_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    referral_partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Deferred is defense in depth if a metadata query selects the model.
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship(
        "Workspace", foreign_keys=[workspace_id], overlaps="logo"
    )
    referral_partner: Mapped["ReferralPartner"] = relationship(
        "ReferralPartner",
        back_populates="logo",
        foreign_keys=[referral_partner_id, workspace_id],
        overlaps="workspace",
    )


# Reciprocal model-only imports stay after the class to avoid import-order cycles.
if TYPE_CHECKING:
    from app.models.referral_partner import ReferralPartner
    from app.models.workspace import Workspace
