"""Adapters from realtor onboarding service results to API response schemas."""

from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException, status

from app.schemas.realtor import (
    ParseCalcomUrlResponse,
    RealtorCampaignResponse,
    RealtorOnboardResponse,
    VerifyCalcomResponse,
)
from app.services.onboarding.exceptions import (
    OnboardingExternalServiceError,
    OnboardingServiceError,
    OnboardingUnprocessableError,
)
from app.services.onboarding.external_checks import CalcomEventTypeLookup, CalcomVerification
from app.services.onboarding.workspace_setup import RealtorCampaignResult, RealtorOnboardingResult


def onboarding_error_to_http_exception(exc: OnboardingServiceError) -> HTTPException:
    """Map onboarding service errors to the legacy realtor endpoint status codes."""
    if isinstance(exc, OnboardingUnprocessableError):
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(exc, OnboardingExternalServiceError):
        status_code = status.HTTP_502_BAD_GATEWAY
    else:
        status_code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=status_code, detail=exc.message)


def raise_onboarding_http_error(exc: OnboardingServiceError) -> NoReturn:
    """Raise the HTTP adapter exception for explicit router exception blocks."""
    raise onboarding_error_to_http_exception(exc) from exc


def realtor_onboard_response(result: RealtorOnboardingResult) -> RealtorOnboardResponse:
    """Build the public onboarding response from the service result."""
    if result.phone_number:
        message = f"Onboarding complete. Phone number {result.phone_number} provisioned."
    else:
        message = (
            "Onboarding complete. No phone number was provisioned — "
            "you can add one from Settings → Phone Numbers."
        )

    return RealtorOnboardResponse(
        workspace_id=result.workspace_id,
        agent_id=result.agent_id,
        phone_number_id=result.phone_number_id,
        phone_number=result.phone_number,
        calcom_connected=result.calcom_connected,
        message=message,
    )


def realtor_campaign_response(result: RealtorCampaignResult) -> RealtorCampaignResponse:
    """Build the public campaign response from the service result."""
    return RealtorCampaignResponse(
        campaign_id=result.campaign_id,
        campaign_name=result.campaign_name,
        campaign_status=result.campaign_status,
        contacts_imported=result.contacts_imported,
        contacts_skipped=result.contacts_skipped,
        contacts_failed=result.contacts_failed,
        phone_number_used=result.phone_number_used,
        agent_id=result.agent_id,
        started_at=result.started_at,
    )


def parse_calcom_url_response(result: CalcomEventTypeLookup) -> ParseCalcomUrlResponse:
    """Build the public Cal.com URL parse response from the service result."""
    return ParseCalcomUrlResponse(
        event_type_id=result.event_type_id,
        slug=result.slug,
        username=result.username,
    )


def verify_calcom_response(result: CalcomVerification) -> VerifyCalcomResponse:
    """Build the public Cal.com verification response from the service result."""
    return VerifyCalcomResponse(valid=result.valid, username=result.username)
