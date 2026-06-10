"""Ad-library service-layer errors.

Subclass the shared :mod:`app.services.exceptions` types so the
``ServiceErrorRoute`` boundary maps them to the right HTTP status (404 / 400 /
503) with the canonical error envelope.
"""

from __future__ import annotations

from typing import ClassVar

from app.services.exceptions import (
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)


class AdLibraryNotFoundError(NotFoundError):
    """A requested ad-library resource (job / advertiser / monitor) is missing."""

    default_code: ClassVar[str] = "ad_library_not_found"


class AdLibraryValidationError(ValidationError):
    """An ad-library request failed a business-rule validation."""

    default_code: ClassVar[str] = "ad_library_validation_error"


class AdLibraryProviderUnavailableError(ServiceUnavailableError):
    """No usable ad-library provider/credentials are configured."""

    default_code: ClassVar[str] = "ad_library_provider_unavailable"
