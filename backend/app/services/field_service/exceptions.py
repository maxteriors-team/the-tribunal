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
