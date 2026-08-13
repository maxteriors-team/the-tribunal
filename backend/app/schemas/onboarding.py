"""Onboarding schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OnboardRequest(BaseModel):
    """Request body for the onboarding endpoint."""

    area_code: str | None = Field(
        None,
        min_length=3,
        max_length=3,
        pattern=r"^\d{3}$",
        description="Optional 3-digit US area code for phone number provisioning",
    )


class OnboardResponse(BaseModel):
    """Response from the onboarding endpoint."""

    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    phone_number_id: uuid.UUID | None
    phone_number: str | None
    phone_provisioned: bool = Field(
        ...,
        description=(
            "True when an SMS-capable phone number was provisioned during onboarding. "
            "When false, the workspace cannot launch SMS/voice campaigns until a number is added."
        ),
    )
    google_calendar_connected: bool
    message: str


class LaunchCampaignResponse(BaseModel):
    """Response from the onboarding CSV-to-campaign endpoint."""

    campaign_id: uuid.UUID
    campaign_name: str
    campaign_status: str
    contacts_imported: int
    contacts_skipped: int
    contacts_failed: int
    phone_number_used: str
    agent_id: uuid.UUID
    started_at: datetime | None
