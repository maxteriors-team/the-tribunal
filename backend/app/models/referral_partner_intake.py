"""Revocable public intake capabilities for an existing referral partner."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.referral_partner import ReferralPartner
    from app.models.workspace import Workspace


class ReferralPartnerIntakeLink(Base, WorkspaceScoped):
    """A time-bounded bearer capability bound to one partner and workspace."""

    __tablename__ = "referral_partner_intake_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["referral_partner_id", "workspace_id"],
            ["referral_partners.id", "referral_partners.workspace_id"],
            name="fk_referral_partner_intake_links_scoped_partner",
            ondelete="CASCADE",
        ),
        Index(
            "ix_referral_partner_intake_links_partner_active",
            "workspace_id",
            "referral_partner_id",
            "revoked_at",
            "expires_at",
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
        UUID(as_uuid=True), nullable=False, index=True
    )

    # Only the digest is used for public lookup. The encrypted bearer value is
    # retained solely so an authorized CRM user can retrieve/copy an active link.
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    token: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped["Workspace"] = relationship(
        "Workspace", foreign_keys=[workspace_id], overlaps="intake_links"
    )
    referral_partner: Mapped["ReferralPartner"] = relationship(
        "ReferralPartner",
        back_populates="intake_links",
        foreign_keys=[referral_partner_id, workspace_id],
        overlaps="workspace",
    )
