"""Workspace-scoped CRUD for business locations (the company's branches)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import select_workspace_owned
from app.models.field_service import BusinessLocation
from app.schemas.field_service import BusinessLocationResponse
from app.services.field_service._refs import get_owned_or_raise
from app.services.field_service.exceptions import (
    BusinessLocationNameConflictError,
    BusinessLocationNotFoundError,
)


class BusinessLocationService:
    """Workspace-scoped CRUD for business locations (branches / business units)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get(self, location_id: uuid.UUID, workspace_id: uuid.UUID) -> BusinessLocation:
        return await get_owned_or_raise(
            self.db,
            BusinessLocation,
            location_id,
            workspace_id,
            BusinessLocationNotFoundError(),
        )

    async def _flush_unique(self) -> None:
        """Flush, translating the (workspace_id, name) unique violation."""
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise BusinessLocationNameConflictError() from exc

    async def list(
        self, workspace_id: uuid.UUID, *, is_active: bool | None = None
    ) -> dict[str, Any]:
        criteria = []
        if is_active is not None:
            criteria.append(BusinessLocation.is_active.is_(is_active))
        query = select_workspace_owned(BusinessLocation, workspace_id, *criteria).order_by(
            BusinessLocation.name
        )
        rows = (await self.db.execute(query)).scalars().all()
        items = [BusinessLocationResponse.model_validate(row) for row in rows]
        return {"items": items, "total": len(items)}

    async def get(
        self, location_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> BusinessLocationResponse:
        return BusinessLocationResponse.model_validate(await self._get(location_id, workspace_id))

    async def create(
        self, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> BusinessLocationResponse:
        location = BusinessLocation(workspace_id=workspace_id, **data)
        self.db.add(location)
        await self._flush_unique()
        await self.db.refresh(location)
        return BusinessLocationResponse.model_validate(location)

    async def update(
        self, location_id: uuid.UUID, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> BusinessLocationResponse:
        location = await self._get(location_id, workspace_id)
        for key, value in data.items():
            setattr(location, key, value)
        await self._flush_unique()
        await self.db.refresh(location)
        return BusinessLocationResponse.model_validate(location)

    async def delete(self, location_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await self.db.delete(await self._get(location_id, workspace_id))
