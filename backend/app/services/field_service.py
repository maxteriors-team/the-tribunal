"""Service layer for field-service entities.

Provides workspace-scoped CRUD for :class:`ServiceLocation`, :class:`Crew`, and
:class:`Technician`. Every read and write is tenant-scoped through
:mod:`app.db.scope`; cross-entity references (a location's contact, a
technician's crew or login) are validated to belong to the same workspace so a
caller cannot bind operational records to another tenant's rows.
"""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import (
    assert_workspace_owned,
    select_workspace_owned,
)
from app.models.contact import Contact
from app.models.field_service import Crew, ServiceLocation, Technician
from app.models.workspace import WorkspaceMembership
from app.schemas.field_service import (
    CrewResponse,
    ServiceLocationResponse,
    TechnicianResponse,
)


async def _assert_contact_in_workspace(
    db: AsyncSession, contact_id: int, workspace_id: uuid.UUID
) -> None:
    """Ensure ``contact_id`` belongs to ``workspace_id`` (tenant-safe 404)."""
    await assert_workspace_owned(db, Contact, contact_id, workspace_id, detail="Contact not found")


async def _assert_crew_in_workspace(
    db: AsyncSession, crew_id: uuid.UUID, workspace_id: uuid.UUID
) -> None:
    """Ensure ``crew_id`` belongs to ``workspace_id`` (tenant-safe 404)."""
    await assert_workspace_owned(db, Crew, crew_id, workspace_id, detail="Crew not found")


async def _assert_user_is_member(db: AsyncSession, user_id: int, workspace_id: uuid.UUID) -> None:
    """Ensure ``user_id`` is a member of ``workspace_id`` before linking a login."""
    result = await db.execute(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a member of this workspace",
        )


class ServiceLocationService:
    """Workspace-scoped CRUD for customer service locations."""

    def __init__(self, db: AsyncSession):
        self.db = db

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
        row = await assert_workspace_owned(
            self.db, ServiceLocation, location_id, workspace_id, detail="Service location not found"
        )
        return ServiceLocationResponse.model_validate(row)

    async def create(
        self, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> ServiceLocationResponse:
        await _assert_contact_in_workspace(self.db, data["contact_id"], workspace_id)
        location = ServiceLocation(workspace_id=workspace_id, **data)
        self.db.add(location)
        await self.db.flush()
        await self.db.refresh(location)
        return ServiceLocationResponse.model_validate(location)

    async def update(
        self, location_id: uuid.UUID, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> ServiceLocationResponse:
        location = await assert_workspace_owned(
            self.db, ServiceLocation, location_id, workspace_id, detail="Service location not found"
        )
        for key, value in data.items():
            setattr(location, key, value)
        await self.db.flush()
        await self.db.refresh(location)
        return ServiceLocationResponse.model_validate(location)

    async def delete(self, location_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        location = await assert_workspace_owned(
            self.db, ServiceLocation, location_id, workspace_id, detail="Service location not found"
        )
        await self.db.delete(location)


class CrewService:
    """Workspace-scoped CRUD for field crews."""

    def __init__(self, db: AsyncSession):
        self.db = db

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

    async def list(
        self, workspace_id: uuid.UUID, *, is_active: bool | None = None
    ) -> dict[str, Any]:
        criteria = []
        if is_active is not None:
            criteria.append(Crew.is_active.is_(is_active))
        query = select_workspace_owned(Crew, workspace_id, *criteria).order_by(Crew.name)
        rows = (await self.db.execute(query)).scalars().all()
        counts = await self._technician_counts(workspace_id, [row.id for row in rows])
        items = []
        for row in rows:
            response = CrewResponse.model_validate(row)
            response.technician_count = counts.get(row.id, 0)
            items.append(response)
        return {"items": items, "total": len(items)}

    async def get(self, crew_id: uuid.UUID, workspace_id: uuid.UUID) -> CrewResponse:
        row = await assert_workspace_owned(
            self.db, Crew, crew_id, workspace_id, detail="Crew not found"
        )
        counts = await self._technician_counts(workspace_id, [row.id])
        response = CrewResponse.model_validate(row)
        response.technician_count = counts.get(row.id, 0)
        return response

    async def create(self, workspace_id: uuid.UUID, data: dict[str, Any]) -> CrewResponse:
        crew = Crew(workspace_id=workspace_id, **data)
        self.db.add(crew)
        try:
            await self.db.flush()
        except IntegrityError as exc:  # unique (workspace_id, name)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A crew with this name already exists",
            ) from exc
        await self.db.refresh(crew)
        response = CrewResponse.model_validate(crew)
        response.technician_count = 0
        return response

    async def update(
        self, crew_id: uuid.UUID, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> CrewResponse:
        crew = await assert_workspace_owned(
            self.db, Crew, crew_id, workspace_id, detail="Crew not found"
        )
        for key, value in data.items():
            setattr(crew, key, value)
        try:
            await self.db.flush()
        except IntegrityError as exc:  # unique (workspace_id, name)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A crew with this name already exists",
            ) from exc
        await self.db.refresh(crew)
        counts = await self._technician_counts(workspace_id, [crew.id])
        response = CrewResponse.model_validate(crew)
        response.technician_count = counts.get(crew.id, 0)
        return response

    async def delete(self, crew_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        crew = await assert_workspace_owned(
            self.db, Crew, crew_id, workspace_id, detail="Crew not found"
        )
        await self.db.delete(crew)


class TechnicianService:
    """Workspace-scoped CRUD for technicians."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _validate_refs(self, workspace_id: uuid.UUID, data: dict[str, Any]) -> None:
        """Validate crew/user references belong to the workspace when provided."""
        crew_id = data.get("crew_id")
        if crew_id is not None:
            await _assert_crew_in_workspace(self.db, crew_id, workspace_id)
        user_id = data.get("user_id")
        if user_id is not None:
            await _assert_user_is_member(self.db, user_id, workspace_id)

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
        row = await assert_workspace_owned(
            self.db, Technician, technician_id, workspace_id, detail="Technician not found"
        )
        return TechnicianResponse.model_validate(row)

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
        technician = await assert_workspace_owned(
            self.db, Technician, technician_id, workspace_id, detail="Technician not found"
        )
        await self._validate_refs(workspace_id, data)
        for key, value in data.items():
            setattr(technician, key, value)
        await self.db.flush()
        await self.db.refresh(technician)
        return TechnicianResponse.model_validate(technician)

    async def delete(self, technician_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        technician = await assert_workspace_owned(
            self.db, Technician, technician_id, workspace_id, detail="Technician not found"
        )
        await self.db.delete(technician)
