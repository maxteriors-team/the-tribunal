"""Field-service domain exceptions.

Raised by the field-service layer instead of coupling to web-framework types
like ``HTTPException``. The API boundary maps these to HTTP responses via
:class:`app.api.service_errors.ServiceErrorRoute`, while non-HTTP callers
(workers, automations, other services) can catch them directly. The HTTP status
each maps to is shown in brackets.
"""

from __future__ import annotations

from app.services.exceptions import ConflictError, NotFoundError, ValidationError


class ServiceLocationNotFoundError(NotFoundError):
    """A service location does not exist in the workspace. [404]"""

    def __init__(self, message: str = "Service location not found") -> None:
        super().__init__(message)


class BusinessLocationNotFoundError(NotFoundError):
    """A business location does not exist in the workspace. [404]"""

    def __init__(self, message: str = "Business location not found") -> None:
        super().__init__(message)


class BusinessLocationNameConflictError(ConflictError):
    """A business location with the same name already exists. [409]"""

    def __init__(self, message: str = "A location with this name already exists") -> None:
        super().__init__(message)


class CrewNotFoundError(NotFoundError):
    """A crew does not exist in the workspace. [404]"""

    def __init__(self, message: str = "Crew not found") -> None:
        super().__init__(message)


class CrewNameConflictError(ConflictError):
    """A crew with the same name already exists in the workspace. [409]"""

    def __init__(self, message: str = "A crew with this name already exists") -> None:
        super().__init__(message)


class TechnicianNotFoundError(NotFoundError):
    """A technician does not exist in the workspace. [404]"""

    def __init__(self, message: str = "Technician not found") -> None:
        super().__init__(message)


class ContactNotInWorkspaceError(NotFoundError):
    """A referenced customer contact does not belong to the workspace. [404]"""

    def __init__(self, message: str = "Contact not found") -> None:
        super().__init__(message)


class UserNotMemberError(ValidationError):
    """A technician's linked login is not a member of the workspace. [400]"""

    def __init__(self, message: str = "User is not a member of this workspace") -> None:
        super().__init__(message)


class JobNotFoundError(NotFoundError):
    """A field-service job does not exist in the workspace. [404]"""

    def __init__(self, message: str = "Job not found") -> None:
        super().__init__(message)


class NeighborOutreachBatchNotFoundError(NotFoundError):
    """No neighbour list has been generated for this job yet. [404]"""

    def __init__(self, message: str = "No neighbor outreach list for this job") -> None:
        super().__init__(message)


class NeighborOutreachEntryNotFoundError(NotFoundError):
    """A neighbour entry does not exist in the workspace. [404]"""

    def __init__(self, message: str = "Neighbor entry not found") -> None:
        super().__init__(message)


class JobSiteNotGeocodedError(ValidationError):
    """The job has no site coordinates, so there is no circle to search. [400]

    ``latitude``/``longitude`` are the only geographic predicate available (the
    postal fields are encrypted and not SQL-queryable), so an ungeocoded site
    cannot produce a neighbour list. Surfaced rather than silently returning an
    empty list, because "no neighbours" and "we don't know where this is" are very
    different answers for an operator.
    """

    def __init__(self, message: str = "Job site has no coordinates to search around") -> None:
        super().__init__(message)


class NeighborMessagingDisabledError(ValidationError):
    """The workspace has not enabled the consent-gated messaging path. [400]"""

    def __init__(self, message: str = "Neighbor messaging is disabled for this workspace") -> None:
        super().__init__(message)


class NeighborCampaignNotFoundError(NotFoundError):
    """The campaign to enroll neighbours into is not in this workspace. [404]"""

    def __init__(self, message: str = "Campaign not found") -> None:
        super().__init__(message)
