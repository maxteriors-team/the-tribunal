"""Typed errors for onboarding service workflows."""

from __future__ import annotations

from app.services.exceptions import ServiceError, ServiceUnavailableError, ValidationError


class OnboardingValidationError(ValidationError):
    """Raised when onboarding input or workspace state is invalid."""


class OnboardingWorkspaceError(OnboardingValidationError):
    """Raised when the user's onboarding workspace cannot be resolved."""


class OnboardingUnprocessableError(OnboardingValidationError):
    """Raised when a syntactically valid request cannot be processed."""


class OnboardingExternalServiceError(ServiceUnavailableError):
    """Raised when an external onboarding dependency cannot be reached."""


OnboardingServiceError = ServiceError
