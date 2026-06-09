"""CRUD service for an agent's bookable staff pool."""

import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crud import get_or_404
from app.models.agent import Agent
from app.models.bookable_staff import BookableStaff
from app.schemas.bookable_staff import (
    BookableStaffCreate,
    BookableStaffList,
    BookableStaffUpdate,
)

logger = structlog.get_logger()


class BookableStaffService:
    """Manage the pool of bookable staff scoped to a workspace + agent."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="bookable_staff_service")

    async def _assert_agent(self, workspace_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        """Ensure the agent exists and belongs to the workspace."""
        return await get_or_404(self.db, Agent, agent_id, workspace_id=workspace_id)

    async def list_staff(
        self,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> BookableStaffList:
        """List all bookable staff for an agent."""
        await self._assert_agent(workspace_id, agent_id)
        result = await self.db.execute(
            select(BookableStaff)
            .where(
                BookableStaff.workspace_id == workspace_id,
                BookableStaff.agent_id == agent_id,
            )
            .order_by(BookableStaff.priority.desc(), BookableStaff.created_at.asc())
        )
        items = list(result.scalars().all())
        return BookableStaffList(items=items, total=len(items))  # type: ignore[arg-type]

    async def create_staff(
        self,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
        body: BookableStaffCreate,
    ) -> BookableStaff:
        """Add a staff member to an agent's pool."""
        await self._assert_agent(workspace_id, agent_id)
        staff = BookableStaff(
            workspace_id=workspace_id,
            agent_id=agent_id,
            **body.model_dump(),
        )
        self.db.add(staff)
        await self.db.commit()
        await self.db.refresh(staff)
        self.log.info(
            "bookable_staff_created",
            staff_id=str(staff.id),
            agent_id=str(agent_id),
            workspace_id=str(workspace_id),
        )
        return staff

    async def update_staff(
        self,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
        staff_id: uuid.UUID,
        body: BookableStaffUpdate,
    ) -> BookableStaff:
        """Update a staff member's config."""
        staff = await self._get_staff(workspace_id, agent_id, staff_id)
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(staff, field, value)
        await self.db.commit()
        await self.db.refresh(staff)
        return staff

    async def delete_staff(
        self,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
        staff_id: uuid.UUID,
    ) -> None:
        """Remove a staff member from the pool."""
        staff = await self._get_staff(workspace_id, agent_id, staff_id)
        await self.db.delete(staff)
        await self.db.commit()

    async def _get_staff(
        self,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
        staff_id: uuid.UUID,
    ) -> BookableStaff:
        result = await self.db.execute(
            select(BookableStaff).where(
                BookableStaff.id == staff_id,
                BookableStaff.workspace_id == workspace_id,
                BookableStaff.agent_id == agent_id,
            )
        )
        staff = result.scalar_one_or_none()
        if staff is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bookable staff not found",
            )
        return staff
