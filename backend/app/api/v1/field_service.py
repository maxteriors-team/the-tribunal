"""Field-service endpoints: service locations, crews, and technicians.

Three routers mounted under a workspace. Reads are available to any workspace
member; writes are role-gated:

- Service locations (customer job sites) — created/edited by dispatchers and up
  (:data:`WorkspaceDispatcher`), since CSRs and dispatchers manage sites.
- Crews and technicians (the field roster) — managed by managers and up
  (:data:`WorkspaceManager`).

Writes run on the transactional session so a failed validation rolls back
cleanly; the role dependency and the transactional session share the same
request-scoped DB session.
"""

import uuid

from fastapi import APIRouter

from app.api.deps import (
    DB,
    TransactionalDB,
    WorkspaceAccess,
    WorkspaceDispatcher,
    WorkspaceManager,
)
from app.schemas.field_service import (
    CrewCreate,
    CrewListResponse,
    CrewResponse,
    CrewUpdate,
    ServiceLocationCreate,
    ServiceLocationListResponse,
    ServiceLocationResponse,
    ServiceLocationUpdate,
    TechnicianCreate,
    TechnicianListResponse,
    TechnicianResponse,
    TechnicianUpdate,
)
from app.services.field_service import (
    CrewService,
    ServiceLocationService,
    TechnicianService,
)

locations_router = APIRouter()
crews_router = APIRouter()
technicians_router = APIRouter()


# --------------------------------------------------------------------------- #
# Service locations
# --------------------------------------------------------------------------- #
@locations_router.get("", response_model=ServiceLocationListResponse)
async def list_service_locations(
    workspace: WorkspaceAccess,
    db: DB,
    contact_id: int | None = None,
    is_active: bool | None = None,
) -> ServiceLocationListResponse:
    """List service locations, optionally filtered by customer or active state."""
    service = ServiceLocationService(db)
    return ServiceLocationListResponse(
        **await service.list(workspace.id, contact_id=contact_id, is_active=is_active)
    )


@locations_router.post("", response_model=ServiceLocationResponse, status_code=201)
async def create_service_location(
    payload: ServiceLocationCreate,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> ServiceLocationResponse:
    """Create a service location for a customer."""
    service = ServiceLocationService(db)
    return await service.create(membership.workspace_id, payload.model_dump())


@locations_router.get("/{location_id}", response_model=ServiceLocationResponse)
async def get_service_location(
    location_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: DB,
) -> ServiceLocationResponse:
    """Get a single service location."""
    service = ServiceLocationService(db)
    return await service.get(location_id, workspace.id)


@locations_router.put("/{location_id}", response_model=ServiceLocationResponse)
async def update_service_location(
    location_id: uuid.UUID,
    payload: ServiceLocationUpdate,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> ServiceLocationResponse:
    """Update a service location."""
    service = ServiceLocationService(db)
    return await service.update(
        location_id, membership.workspace_id, payload.model_dump(exclude_unset=True)
    )


@locations_router.delete("/{location_id}", status_code=204)
async def delete_service_location(
    location_id: uuid.UUID,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> None:
    """Delete a service location."""
    service = ServiceLocationService(db)
    await service.delete(location_id, membership.workspace_id)


# --------------------------------------------------------------------------- #
# Crews
# --------------------------------------------------------------------------- #
@crews_router.get("", response_model=CrewListResponse)
async def list_crews(
    workspace: WorkspaceAccess,
    db: DB,
    is_active: bool | None = None,
) -> CrewListResponse:
    """List crews with active-technician counts."""
    service = CrewService(db)
    return CrewListResponse(**await service.list(workspace.id, is_active=is_active))


@crews_router.post("", response_model=CrewResponse, status_code=201)
async def create_crew(
    payload: CrewCreate,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> CrewResponse:
    """Create a crew."""
    service = CrewService(db)
    return await service.create(membership.workspace_id, payload.model_dump())


@crews_router.get("/{crew_id}", response_model=CrewResponse)
async def get_crew(
    crew_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: DB,
) -> CrewResponse:
    """Get a single crew."""
    service = CrewService(db)
    return await service.get(crew_id, workspace.id)


@crews_router.put("/{crew_id}", response_model=CrewResponse)
async def update_crew(
    crew_id: uuid.UUID,
    payload: CrewUpdate,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> CrewResponse:
    """Update a crew."""
    service = CrewService(db)
    return await service.update(
        crew_id, membership.workspace_id, payload.model_dump(exclude_unset=True)
    )


@crews_router.delete("/{crew_id}", status_code=204)
async def delete_crew(
    crew_id: uuid.UUID,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> None:
    """Delete a crew. Assigned technicians are unassigned (crew set to null)."""
    service = CrewService(db)
    await service.delete(crew_id, membership.workspace_id)


# --------------------------------------------------------------------------- #
# Technicians
# --------------------------------------------------------------------------- #
@technicians_router.get("", response_model=TechnicianListResponse)
async def list_technicians(
    workspace: WorkspaceAccess,
    db: DB,
    crew_id: uuid.UUID | None = None,
    is_active: bool | None = None,
) -> TechnicianListResponse:
    """List technicians, optionally filtered by crew or active state."""
    service = TechnicianService(db)
    return TechnicianListResponse(
        **await service.list(workspace.id, crew_id=crew_id, is_active=is_active)
    )


@technicians_router.post("", response_model=TechnicianResponse, status_code=201)
async def create_technician(
    payload: TechnicianCreate,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> TechnicianResponse:
    """Create a technician."""
    service = TechnicianService(db)
    return await service.create(membership.workspace_id, payload.model_dump())


@technicians_router.get("/{technician_id}", response_model=TechnicianResponse)
async def get_technician(
    technician_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: DB,
) -> TechnicianResponse:
    """Get a single technician."""
    service = TechnicianService(db)
    return await service.get(technician_id, workspace.id)


@technicians_router.put("/{technician_id}", response_model=TechnicianResponse)
async def update_technician(
    technician_id: uuid.UUID,
    payload: TechnicianUpdate,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> TechnicianResponse:
    """Update a technician."""
    service = TechnicianService(db)
    return await service.update(
        technician_id, membership.workspace_id, payload.model_dump(exclude_unset=True)
    )


@technicians_router.delete("/{technician_id}", status_code=204)
async def delete_technician(
    technician_id: uuid.UUID,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> None:
    """Delete a technician."""
    service = TechnicianService(db)
    await service.delete(technician_id, membership.workspace_id)
