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

from app.services.field_service.business_locations import BusinessLocationService
from app.services.field_service.crews import CrewService
from app.services.field_service.exceptions import (
    BusinessLocationNameConflictError,
    BusinessLocationNotFoundError,
    ContactNotInWorkspaceError,
    CrewNameConflictError,
    CrewNotFoundError,
    JobNotFoundError,
    JobSiteNotGeocodedError,
    NeighborCampaignNotFoundError,
    NeighborMessagingDisabledError,
    NeighborOutreachBatchNotFoundError,
    NeighborOutreachEntryNotFoundError,
    ServiceLocationNotFoundError,
    TechnicianNotFoundError,
    UserNotMemberError,
)
from app.services.field_service.locations import ServiceLocationService
from app.services.field_service.roster import (
    FIELD_ROLES,
    ensure_member_on_roster,
    is_field_role,
    retire_member_from_roster,
)
from app.services.field_service.technicians import TechnicianService

# NOTE: ``NeighborOutreachService`` is deliberately **not** re-exported here.
# ``app.schemas.neighbor_outreach`` reads its radius bounds from
# ``.jobsite_radius``, and importing any submodule of this package executes this
# ``__init__``. Re-exporting the service would therefore make
# schemas -> package init -> service -> schemas a hard circular import. Import it
# from ``app.services.field_service.neighbor_outreach`` directly.

__all__ = [
    "FIELD_ROLES",
    "ensure_member_on_roster",
    "is_field_role",
    "retire_member_from_roster",
    "BusinessLocationService",
    "ServiceLocationService",
    "CrewService",
    "TechnicianService",
    "BusinessLocationNotFoundError",
    "BusinessLocationNameConflictError",
    "ServiceLocationNotFoundError",
    "CrewNotFoundError",
    "CrewNameConflictError",
    "TechnicianNotFoundError",
    "ContactNotInWorkspaceError",
    "UserNotMemberError",
    "JobNotFoundError",
    "JobSiteNotGeocodedError",
    "NeighborOutreachBatchNotFoundError",
    "NeighborOutreachEntryNotFoundError",
    "NeighborMessagingDisabledError",
    "NeighborCampaignNotFoundError",
]
