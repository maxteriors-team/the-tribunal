"""Private handoff images attached directly to a job."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped
from app.models.quote_handoff_image import HANDOFF_IMAGE_CONTENT_TYPES, MAX_HANDOFF_IMAGE_BYTES


class JobHandoffImage(Base, WorkspaceScoped):
    """A bounded office-uploaded image stored for a job's field team."""

    __tablename__ = "job_handoff_images"
    __table_args__ = (
        CheckConstraint(
            f"content_type IN {HANDOFF_IMAGE_CONTENT_TYPES}",
            name="content_type",
        ),
        CheckConstraint(
            f"size_bytes > 0 AND size_bytes <= {MAX_HANDOFF_IMAGE_BYTES}",
            name="size",
        ),
        CheckConstraint(
            "octet_length(data) = size_bytes",
            name="data_size",
        ),
        Index(
            "ix_job_handoff_images_workspace_job_created",
            "workspace_id",
            "job_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_service_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    @property
    def source(self) -> str:
        """Identify this row's immutable storage owner in API metadata."""
        return "job"
