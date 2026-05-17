"""Pipeline model for sales/service pipeline management."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.opportunity import Opportunity
    from app.models.workspace import Workspace


class Pipeline(Base):
    """Sales/service pipeline container."""

    __tablename__ = "pipelines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="pipelines")
    stages: Mapped[list["PipelineStage"]] = relationship(
        "PipelineStage", back_populates="pipeline", cascade="all, delete-orphan"
    )
    opportunities: Mapped[list["Opportunity"]] = relationship(
        "Opportunity", back_populates="pipeline", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Pipeline(id={self.id}, name={self.name})>"


class PipelineStage(Base):
    """Stage within a pipeline."""

    __tablename__ = "pipeline_stages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Configuration
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    probability: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0-100

    # Type classification
    stage_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )  # active, won, lost

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
    pipeline: Mapped["Pipeline"] = relationship("Pipeline", back_populates="stages")
    opportunities: Mapped[list["Opportunity"]] = relationship(
        "Opportunity", back_populates="stage", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<PipelineStage(id={self.id}, name={self.name}, order={self.order})>"
