"""Integration credential schemas."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

IntegrationType = Literal[
    "calcom",
    "telnyx",
    "openai",
    "resend",
    "meta_ad_library",
    "google_ads_transparency",
]


class IntegrationCredentialsBase(BaseModel):
    """Base schema for integration credentials."""

    api_key: str = Field(..., min_length=1, description="API key for the integration")


class CalcomCredentials(IntegrationCredentialsBase):
    """Cal.com specific credentials."""

    event_type_id: str | None = Field(None, description="Default event type ID for bookings")


class TelnyxCredentials(IntegrationCredentialsBase):
    """Telnyx specific credentials."""

    messaging_profile_id: str | None = Field(None, description="Messaging profile ID")
    phone_number: str | None = Field(None, description="Default phone number")


class OpenAICredentials(BaseModel):
    """OpenAI specific credentials."""

    api_key: str | None = Field(None, description="OpenAI API key")
    access_token: str | None = Field(None, description="OpenAI OAuth access token")
    refresh_token: str | None = Field(None, description="OpenAI OAuth refresh token")
    expires_at: int | None = Field(None, description="OAuth token expiry as epoch milliseconds")
    account_id: str | None = Field(None, description="OpenAI account ID")
    organization_id: str | None = Field(None, description="OpenAI organization ID")


class ResendCredentials(IntegrationCredentialsBase):
    """Resend specific credentials."""

    from_email: str | None = Field(None, description="Default sender email address")
    from_name: str | None = Field(None, description="Default sender name")


class MetaAdLibraryCredentials(BaseModel):
    """Meta Ad Library specific credentials.

    ``access_token`` is a Meta developer-app token with ``ads_read``. The Ad
    Library is public data. Optional ``thirdparty_*`` fields configure a
    config-gated fallback provider (Apify / ScrapeCreators / SerpApi) for
    fuller US-commercial coverage.
    """

    access_token: str = Field(..., min_length=1, description="Meta app access token (ads_read)")
    default_country: str | None = Field(None, description="Default ad_reached_countries (e.g. US)")
    thirdparty_provider: str | None = Field(
        None, description="Fallback provider: apify | scrapecreators | serpapi"
    )
    thirdparty_api_key: str | None = Field(None, description="Fallback provider API key")


class GoogleAdsTransparencyCredentials(BaseModel):
    """Google Ads Transparency Center credentials.

    No official API exists; the SerpApi adapter is the supported path. ``api_key``
    is the SerpApi key.
    """

    api_key: str = Field(..., min_length=1, description="SerpApi API key")


class IntegrationCreate(BaseModel):
    """Schema for creating/updating an integration."""

    integration_type: IntegrationType
    credentials: dict[str, Any] = Field(..., description="Integration-specific credentials")
    is_active: bool = Field(default=True)


class IntegrationUpdate(BaseModel):
    """Schema for updating an integration."""

    credentials: dict[str, Any] | None = Field(None, description="Integration-specific credentials")
    is_active: bool | None = None


class IntegrationResponse(BaseModel):
    """Schema for integration response."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    integration_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Note: credentials are not returned in responses for security

    model_config = {"from_attributes": True}


class IntegrationWithMaskedCredentials(IntegrationResponse):
    """Schema for integration response with masked credentials."""

    masked_credentials: dict[str, str] = Field(
        default_factory=dict,
        description="Masked credential keys (e.g., 'sk_****1234')",
    )


class IntegrationTestResult(BaseModel):
    """Schema for integration test result."""

    success: bool
    message: str
    details: dict[str, Any] | None = None
