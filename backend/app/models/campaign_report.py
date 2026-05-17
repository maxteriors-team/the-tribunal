"""CampaignReport model - AI-generated post-mortem analysis of completed campaigns."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CampaignReport(Base):
    """AI-generated intelligence report for a completed campaign."""

    __tablename__ = "campaign_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="generating", index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Structured report fields
    metrics_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    executive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_findings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    what_worked: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    what_didnt_work: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    recommendations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    segment_analysis: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    timing_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    prompt_performance: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    generated_suggestion_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<CampaignReport(id={self.id}, campaign_id={self.campaign_id}, status={self.status})>"
        )
