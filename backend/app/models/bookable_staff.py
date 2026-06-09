"""Bookable staff / resource model.

A pool of bookable staff members (or resources) that the AI booking tool can
assign appointments to instead of always binding to a single Cal.com event type
per agent. Each staff member carries:

- their own Cal.com event type / schedule (``calcom_event_type_id``)
- a set of ``skills`` used for skill-based routing
- round-robin distribution counters (``assignment_count`` / ``last_assigned_at``)

Selection is driven by the owning agent's ``assignment_strategy`` (see
:class:`app.models.agent.Agent`) via
:mod:`app.services.calendar.staff_assignment`.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.dialects.postgresql import TEXT as PG_TEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.workspace import Workspace


class BookableStaff(Base):
    """A bookable staff member / resource within a workspace.

    Scoped to a workspace and (optionally) a specific agent's pool. When
    ``agent_id`` is set the staff member belongs to that agent's booking pool;
    the booking tool only assigns from staff matching the active agent.
    """

    __tablename__ = "bookable_staff"
    __table_args__ = (
        Index(
            "ix_bookable_staff_workspace_agent_active",
            "workspace_id",
            "agent_id",
            "is_active",
        ),
        Index(
            "ix_bookable_staff_calcom_event_type_id",
            "calcom_event_type_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Identity
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Each staff member books against their own Cal.com event type / schedule.
    calcom_event_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Skill tags used for skill-based routing (case-insensitive matching).
    skills: Mapped[list[str]] = mapped_column(ARRAY(PG_TEXT), default=list, nullable=False)

    # Whether this staff member is in the active assignment pool.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # Higher priority wins round-robin ties (e.g. preferred staff).
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    # Round-robin distribution tracking.
    assignment_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    last_assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="bookable_staff")
    agent: Mapped["Agent | None"] = relationship("Agent", back_populates="bookable_staff")

    def __repr__(self) -> str:
        return f"<BookableStaff(id={self.id}, name={self.name}, skills={self.skills})>"
