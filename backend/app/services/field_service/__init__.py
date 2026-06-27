"""Field-service domain: service locations, crews, and technicians.

Workspace-scoped CRUD for the field-service entities, split one service per
file. Every read and write is tenant-scoped through :mod:`app.db.scope`, and
cross-entity references (a location's contact, a technician's crew or login) are
validated to belong to the same workspace so a caller cannot bind operational
records to another tenant's rows.

The services raise typed errors from :mod:`.exceptions` (a ``ServiceError``
subclass hierarchy) rather than ``HTTPException`` — so they are reusable from
workers, automations, and other services, not just HTTP routes. The API layer
maps those errors to responses via
:class:`app.api.service_errors.ServiceErrorRoute`.
"""

from app.services.field_service.crews import CrewService
from app.services.field_service.exceptions import (
    ContactNotInWorkspaceError,
    CrewNameConflictError,
    CrewNotFoundError,
    ServiceLocationNotFoundError,
    TechnicianNotFoundError,
    UserNotMemberError,
)
from app.services.field_service.locations import ServiceLocationService
from app.services.field_service.technicians import TechnicianService

__all__ = [
    "ServiceLocationService",
    "CrewService",
    "TechnicianService",
    "ServiceLocationNotFoundError",
    "CrewNotFoundError",
    "CrewNameConflictError",
    "TechnicianNotFoundError",
    "ContactNotInWorkspaceError",
    "UserNotMemberError",
]
