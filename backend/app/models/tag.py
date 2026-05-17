"""Tag model and ContactTag join table."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact


class Tag(Base):
    """Workspace-level tag with color."""

    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6366f1")

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
    contact_tags: Mapped[list["ContactTag"]] = relationship(
        "ContactTag", back_populates="tag", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_tags_workspace_name"),)

    def __repr__(self) -> str:
        return f"<Tag(id={self.id}, name={self.name}, color={self.color})>"


class ContactTag(Base):
    """Join table between contacts and tags."""

    __tablename__ = "contact_tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    contact: Mapped["Contact"] = relationship("Contact", back_populates="contact_tags")
    tag: Mapped["Tag"] = relationship("Tag", back_populates="contact_tags")

    __table_args__ = (UniqueConstraint("contact_id", "tag_id", name="uq_contact_tags_contact_tag"),)

    def __repr__(self) -> str:
        return f"<ContactTag(contact_id={self.contact_id}, tag_id={self.tag_id})>"
