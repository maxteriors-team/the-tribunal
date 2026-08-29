"""Workspace-scoped landscape lighting design projects."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.field_service import Job, ServiceLocation
    from app.models.opportunity import Opportunity
    from app.models.quote import Quote
    from app.models.user import User
    from app.models.workspace import Workspace


LIGHTING_PROJECT_STATUSES = ("active", "archived")


class LightingProject(Base, WorkspaceScoped):
    """The current, versioned landscape design for one CRM customer project."""

    __tablename__ = "lighting_projects"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_lighting_projects_status"),
        CheckConstraint("version > 0", name="ck_lighting_projects_version_positive"),
        Index(
            "ix_lighting_projects_workspace_status_updated",
            "workspace_id",
            "status",
            "updated_at",
        ),
        Index("ix_lighting_projects_workspace_contact", "workspace_id", "contact_id"),
        Index("ix_lighting_projects_workspace_opportunity", "workspace_id", "opportunity_id"),
        Index("ix_lighting_projects_workspace_assignee", "workspace_id", "assigned_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    service_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Stable ID of the operator-selected sheet inside the validated v2 document.
    # The service validates this application-level reference whenever it changes.
    installation_shot_id: Mapped[str | None] = mapped_column(String(250), nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    workspace: Mapped["Workspace"] = relationship("Workspace")
    contact: Mapped["Contact"] = relationship("Contact")
    service_location: Mapped["ServiceLocation | None"] = relationship("ServiceLocation")
    opportunity: Mapped["Opportunity | None"] = relationship("Opportunity")
    assignee: Mapped["User | None"] = relationship("User", foreign_keys=[assigned_user_id])
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])
    updated_by: Mapped["User | None"] = relationship("User", foreign_keys=[updated_by_id])
    quotes: Mapped[list["Quote"]] = relationship(
        "Quote", back_populates="lighting_project", foreign_keys="Quote.lighting_project_id"
    )
    jobs: Mapped[list["Job"]] = relationship(
        "Job", back_populates="lighting_project", foreign_keys="Job.lighting_project_id"
    )

    def __repr__(self) -> str:
        return f"<LightingProject(id={self.id}, name={self.name!r}, version={self.version})>"
