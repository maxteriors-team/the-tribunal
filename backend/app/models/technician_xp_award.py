"""Durable, idempotent XP awards for the technician Lighting League."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

TECHNICIAN_XP_CATEGORIES = ("attendance", "job", "upsell")


class TechnicianXpAward(Base, WorkspaceScoped):
    """One reversible XP award tied to an authoritative business event."""

    __tablename__ = "technician_xp_awards"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "technician_id",
            "category",
            "source_key",
            name="uq_technician_xp_awards_source",
        ),
        CheckConstraint(
            f"category IN {TECHNICIAN_XP_CATEGORIES}",
            name="ck_technician_xp_awards_category",
        ),
        CheckConstraint("points > 0", name="ck_technician_xp_awards_points_positive"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= awarded_at",
            name="ck_technician_xp_awards_revocation_order",
        ),
        Index(
            "ix_technician_xp_awards_workspace_awarded_active",
            "workspace_id",
            "awarded_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_technician_xp_awards_workspace_technician_active",
            "workspace_id",
            "technician_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    technician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("technicians.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("now()"),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
