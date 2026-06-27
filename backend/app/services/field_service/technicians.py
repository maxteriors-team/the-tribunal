"""Workspace-scoped CRUD for technicians (the field roster)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import select_workspace_owned
from app.models.field_service import Technician
from app.schemas.field_service import TechnicianResponse
from app.services.field_service._refs import (
    assert_crew_in_workspace,
    assert_user_is_member,
    get_owned_or_raise,
)
from app.services.field_service.exceptions import TechnicianNotFoundError


class TechnicianService:
    """Workspace-scoped CRUD for technicians."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get(self, technician_id: uuid.UUID, workspace_id: uuid.UUID) -> Technician:
        return await get_owned_or_raise(
            self.db, Technician, technician_id, workspace_id, TechnicianNotFoundError()
        )

    async def _validate_refs(self, workspace_id: uuid.UUID, data: dict[str, Any]) -> None:
        """Validate crew/user references belong to the workspace when provided."""
        crew_id = data.get("crew_id")
        if crew_id is not None:
            await assert_crew_in_workspace(self.db, crew_id, workspace_id)
        user_id = data.get("user_id")
        if user_id is not None:
            await assert_user_is_member(self.db, user_id, workspace_id)

    async def list(
        self,
        workspace_id: uuid.UUID,
        *,
        crew_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        criteria = []
        if crew_id is not None:
            criteria.append(Technician.crew_id == crew_id)
        if is_active is not None:
            criteria.append(Technician.is_active.is_(is_active))
        query = select_workspace_owned(Technician, workspace_id, *criteria).order_by(
            Technician.name
        )
        rows = (await self.db.execute(query)).scalars().all()
        items = [TechnicianResponse.model_validate(row) for row in rows]
        return {"items": items, "total": len(items)}

    async def get(self, technician_id: uuid.UUID, workspace_id: uuid.UUID) -> TechnicianResponse:
        return TechnicianResponse.model_validate(await self._get(technician_id, workspace_id))

    async def create(self, workspace_id: uuid.UUID, data: dict[str, Any]) -> TechnicianResponse:
        await self._validate_refs(workspace_id, data)
        technician = Technician(workspace_id=workspace_id, **data)
        self.db.add(technician)
        await self.db.flush()
        await self.db.refresh(technician)
        return TechnicianResponse.model_validate(technician)

    async def update(
        self, technician_id: uuid.UUID, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> TechnicianResponse:
        technician = await self._get(technician_id, workspace_id)
        await self._validate_refs(workspace_id, data)
        for key, value in data.items():
            setattr(technician, key, value)
        await self.db.flush()
        await self.db.refresh(technician)
        return TechnicianResponse.model_validate(technician)

    async def delete(self, technician_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await self.db.delete(await self._get(technician_id, workspace_id))
