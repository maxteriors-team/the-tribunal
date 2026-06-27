"""Workspace-scoped CRUD for customer service locations (job sites)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import select_workspace_owned
from app.models.field_service import ServiceLocation
from app.schemas.field_service import ServiceLocationResponse
from app.services.field_service._refs import (
    assert_contact_in_workspace,
    get_owned_or_raise,
)
from app.services.field_service.exceptions import ServiceLocationNotFoundError


class ServiceLocationService:
    """Workspace-scoped CRUD for customer service locations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get(self, location_id: uuid.UUID, workspace_id: uuid.UUID) -> ServiceLocation:
        return await get_owned_or_raise(
            self.db, ServiceLocation, location_id, workspace_id, ServiceLocationNotFoundError()
        )

    async def list(
        self,
        workspace_id: uuid.UUID,
        *,
        contact_id: int | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        criteria = []
        if contact_id is not None:
            criteria.append(ServiceLocation.contact_id == contact_id)
        if is_active is not None:
            criteria.append(ServiceLocation.is_active.is_(is_active))
        query = select_workspace_owned(ServiceLocation, workspace_id, *criteria).order_by(
            ServiceLocation.created_at.desc()
        )
        rows = (await self.db.execute(query)).scalars().all()
        items = [ServiceLocationResponse.model_validate(row) for row in rows]
        return {"items": items, "total": len(items)}

    async def get(self, location_id: uuid.UUID, workspace_id: uuid.UUID) -> ServiceLocationResponse:
        return ServiceLocationResponse.model_validate(await self._get(location_id, workspace_id))

    async def create(
        self, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> ServiceLocationResponse:
        await assert_contact_in_workspace(self.db, data["contact_id"], workspace_id)
        location = ServiceLocation(workspace_id=workspace_id, **data)
        self.db.add(location)
        await self.db.flush()
        await self.db.refresh(location)
        return ServiceLocationResponse.model_validate(location)

    async def update(
        self, location_id: uuid.UUID, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> ServiceLocationResponse:
        location = await self._get(location_id, workspace_id)
        for key, value in data.items():
            setattr(location, key, value)
        await self.db.flush()
        await self.db.refresh(location)
        return ServiceLocationResponse.model_validate(location)

    async def delete(self, location_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await self.db.delete(await self._get(location_id, workspace_id))
