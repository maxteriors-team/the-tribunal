"""Workspace-scoped CRUD for field crews (dispatch lanes)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import select_workspace_owned
from app.models.field_service import Crew, Technician
from app.schemas.field_service import CrewResponse
from app.services.field_service._refs import get_owned_or_raise
from app.services.field_service.exceptions import CrewNameConflictError, CrewNotFoundError


class CrewService:
    """Workspace-scoped CRUD for field crews."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get(self, crew_id: uuid.UUID, workspace_id: uuid.UUID) -> Crew:
        return await get_owned_or_raise(self.db, Crew, crew_id, workspace_id, CrewNotFoundError())

    async def _technician_counts(
        self, workspace_id: uuid.UUID, crew_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Active-technician counts per crew, in one grouped query."""
        if not crew_ids:
            return {}
        result = await self.db.execute(
            select(Technician.crew_id, func.count(Technician.id))
            .where(
                Technician.workspace_id == workspace_id,
                Technician.crew_id.in_(crew_ids),
            )
            .group_by(Technician.crew_id)
        )
        return {row[0]: row[1] for row in result.all() if row[0] is not None}

    def _to_response(self, crew: Crew, count: int) -> CrewResponse:
        response = CrewResponse.model_validate(crew)
        response.technician_count = count
        return response

    async def _flush_unique(self) -> None:
        """Flush, translating the (workspace_id, name) unique violation."""
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise CrewNameConflictError() from exc

    async def list(
        self, workspace_id: uuid.UUID, *, is_active: bool | None = None
    ) -> dict[str, Any]:
        criteria = []
        if is_active is not None:
            criteria.append(Crew.is_active.is_(is_active))
        query = select_workspace_owned(Crew, workspace_id, *criteria).order_by(Crew.name)
        rows = (await self.db.execute(query)).scalars().all()
        counts = await self._technician_counts(workspace_id, [row.id for row in rows])
        items = [self._to_response(row, counts.get(row.id, 0)) for row in rows]
        return {"items": items, "total": len(items)}

    async def get(self, crew_id: uuid.UUID, workspace_id: uuid.UUID) -> CrewResponse:
        crew = await self._get(crew_id, workspace_id)
        counts = await self._technician_counts(workspace_id, [crew.id])
        return self._to_response(crew, counts.get(crew.id, 0))

    async def create(self, workspace_id: uuid.UUID, data: dict[str, Any]) -> CrewResponse:
        crew = Crew(workspace_id=workspace_id, **data)
        self.db.add(crew)
        await self._flush_unique()
        await self.db.refresh(crew)
        return self._to_response(crew, 0)

    async def update(
        self, crew_id: uuid.UUID, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> CrewResponse:
        crew = await self._get(crew_id, workspace_id)
        for key, value in data.items():
            setattr(crew, key, value)
        await self._flush_unique()
        await self.db.refresh(crew)
        counts = await self._technician_counts(workspace_id, [crew.id])
        return self._to_response(crew, counts.get(crew.id, 0))

    async def delete(self, crew_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await self.db.delete(await self._get(crew_id, workspace_id))
