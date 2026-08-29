"""Workspace and membership models."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import InvalidToken, decrypt_json, encrypt_json
from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

logger = structlog.get_logger()

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.appointment import Appointment
    from app.models.automation import Automation
    from app.models.bookable_staff import BookableStaff
    from app.models.campaign import Campaign
    from app.models.contact import Contact
    from app.models.conversation import Conversation
    from app.models.email_template import EmailTemplate
    from app.models.field_service import BusinessLocation, Crew, ServiceLocation, Technician
    from app.models.lead_magnet import LeadMagnet
    from app.models.message_template import MessageTemplate
    from app.models.message_test import MessageTest
    from app.models.offer import Offer
    from app.models.opportunity import Opportunity
    from app.models.phone_number import PhoneNumber
    from app.models.pipeline import Pipeline
    from app.models.user import User


class Workspace(Base):
    """Workspace for multi-tenant isolation."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # timezone, business_hours
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # When the operator actually finished the self-serve onboarding wizard
    # (:func:`app.services.onboarding.workspace_setup.complete_onboarding`).
    # ``None`` means "never onboarded" and is the only signal the setup gate may
    # key off. Do not infer setup state from rows the system seeds on the
    # operator's behalf (the default agent, the default pipeline): a workspace
    # created through ``POST /workspaces`` owns a template agent at birth, so
    # "has an agent" reported "configured" seconds after creation and made the
    # onboarding funnel unreachable for every UI-created workspace.
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    # Relationships
    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership", back_populates="workspace", cascade="all, delete-orphan"
    )
    integrations: Mapped[list["WorkspaceIntegration"]] = relationship(
        "WorkspaceIntegration", back_populates="workspace", cascade="all, delete-orphan"
    )
    contacts: Mapped[list["Contact"]] = relationship(
        "Contact", back_populates="workspace", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="workspace", cascade="all, delete-orphan"
    )
    agents: Mapped[list["Agent"]] = relationship(
        "Agent", back_populates="workspace", cascade="all, delete-orphan"
    )
    campaigns: Mapped[list["Campaign"]] = relationship(
        "Campaign", back_populates="workspace", cascade="all, delete-orphan"
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment", back_populates="workspace", cascade="all, delete-orphan"
    )
    bookable_staff: Mapped[list["BookableStaff"]] = relationship(
        "BookableStaff", back_populates="workspace", cascade="all, delete-orphan"
    )
    phone_numbers: Mapped[list["PhoneNumber"]] = relationship(
        "PhoneNumber", back_populates="workspace", cascade="all, delete-orphan"
    )
    offers: Mapped[list["Offer"]] = relationship(
        "Offer", back_populates="workspace", cascade="all, delete-orphan"
    )
    lead_magnets: Mapped[list["LeadMagnet"]] = relationship(
        "LeadMagnet", back_populates="workspace", cascade="all, delete-orphan"
    )
    automations: Mapped[list["Automation"]] = relationship(
        "Automation", back_populates="workspace", cascade="all, delete-orphan"
    )
    pipelines: Mapped[list["Pipeline"]] = relationship(
        "Pipeline", back_populates="workspace", cascade="all, delete-orphan"
    )
    opportunities: Mapped[list["Opportunity"]] = relationship(
        "Opportunity", back_populates="workspace", cascade="all, delete-orphan"
    )
    message_tests: Mapped[list["MessageTest"]] = relationship(
        "MessageTest", back_populates="workspace", cascade="all, delete-orphan"
    )
    message_templates: Mapped[list["MessageTemplate"]] = relationship(
        "MessageTemplate", back_populates="workspace", cascade="all, delete-orphan"
    )
    email_templates: Mapped[list["EmailTemplate"]] = relationship(
        "EmailTemplate", back_populates="workspace", cascade="all, delete-orphan"
    )
    business_locations: Mapped[list["BusinessLocation"]] = relationship(
        "BusinessLocation", back_populates="workspace", cascade="all, delete-orphan"
    )
    service_locations: Mapped[list["ServiceLocation"]] = relationship(
        "ServiceLocation", back_populates="workspace", cascade="all, delete-orphan"
    )
    crews: Mapped[list["Crew"]] = relationship(
        "Crew", back_populates="workspace", cascade="all, delete-orphan"
    )
    technicians: Mapped[list["Technician"]] = relationship(
        "Technician", back_populates="workspace", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Workspace(id={self.id}, slug={self.slug})>"


class WorkspaceMembership(Base, WorkspaceScoped):
    """User membership in a workspace."""

    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", name="uq_user_workspace"),
        # A user has at most one default membership. Partial, because they may
        # hold any number of non-default ones. Writers must clear before
        # promoting (a partial unique index cannot be DEFERRABLE in Postgres) —
        # see app.services.workspaces.membership.set_default_membership.
        Index(
            "uq_workspace_membership_default_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="member"
    )  # owner, admin, member
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="memberships")
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="memberships")

    def __repr__(self) -> str:
        return (
            f"<WorkspaceMembership(user_id={self.user_id}, "
            f"workspace_id={self.workspace_id}, role={self.role})>"
        )


class WorkspaceIntegration(Base, WorkspaceScoped):
    """Integration credentials for a workspace."""

    __tablename__ = "workspace_integrations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "integration_type", name="uq_workspace_integration"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    integration_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # telnyx, openai, resend, companycam, lead-source integrations
    encrypted_credentials: Mapped[str] = mapped_column(
        "credentials", Text, nullable=False
    )  # Fernet-encrypted JSON
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="integrations")

    @property
    def credentials(self) -> dict[str, Any]:
        """Decrypt and return credentials dict."""
        return decrypt_json(self.encrypted_credentials)

    @credentials.setter
    def credentials(self, value: dict[str, Any]) -> None:
        """Encrypt and store credentials dict."""
        self.encrypted_credentials = encrypt_json(value)

    def safe_credentials(self) -> dict[str, Any] | None:
        """Decrypt credentials, returning ``None`` instead of raising on failure.

        A corrupted blob or an encryption-key rotation makes :attr:`credentials`
        raise ``InvalidToken``/``ValueError``. Read paths that surface integration
        status (settings/integrations listings) must not turn one unreadable row
        into a 500 that takes down the whole settings page, so they use this and
        treat ``None`` as "present but unreadable".
        """
        try:
            return self.credentials
        except (InvalidToken, ValueError, TypeError) as exc:
            logger.warning(
                "integration_credentials_decrypt_failed",
                workspace_id=str(self.workspace_id),
                integration_type=self.integration_type,
                error=str(exc),
            )
            return None

    def __repr__(self) -> str:
        return (
            f"<WorkspaceIntegration(workspace_id={self.workspace_id}, "
            f"type={self.integration_type})>"
        )
