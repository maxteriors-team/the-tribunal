"""Typed errors for onboarding service workflows."""

from __future__ import annotations

from app.services.exceptions import (
    PermissionDeniedError,
    ServiceError,
    ServiceUnavailableError,
    ValidationError,
)


class OnboardingValidationError(ValidationError):
    """Raised when onboarding input or workspace state is invalid."""


class OnboardingPermissionError(PermissionDeniedError):
    """Raised when the caller may not run onboarding against its workspace."""


class OnboardingWorkspaceError(OnboardingValidationError):
    """Raised when the user's onboarding workspace cannot be resolved."""


class OnboardingUnprocessableError(OnboardingValidationError):
    """Raised when a syntactically valid request cannot be processed."""


class OnboardingExternalServiceError(ServiceUnavailableError):
    """Raised when an external onboarding dependency cannot be reached."""


OnboardingServiceError = ServiceError
