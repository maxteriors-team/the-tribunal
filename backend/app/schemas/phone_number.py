"""Phone number schemas for phone number management endpoints."""

import uuid
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.lead_source import LeadSourceType
from app.models.phone_number import is_mms_capable
from app.utils.phone import PhoneNumberError, normalize_phone_e164


class PhoneNumberLeadSourceResponse(BaseModel):
    """Lead-source identity displayed beside a tracking number."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: LeadSourceType


class PhoneNumberLeadSourceCampaignResponse(BaseModel):
    """Campaign identity displayed beside a tracking number."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class PhoneNumberResponse(BaseModel):
    """Phone number response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    phone_number: str
    friendly_name: str | None
    provider: str
    sms_enabled: bool
    voice_enabled: bool
    mms_enabled: bool
    imessage_enabled: bool
    mac_relay_sender_id: str | None
    mac_relay_service: str
    assigned_agent_id: uuid.UUID | None
    inbound_ai_enabled: bool = False
    lead_source_id: uuid.UUID | None
    lead_source_campaign_id: uuid.UUID | None
    tracking_label: str | None
    lead_source: PhoneNumberLeadSourceResponse | None
    lead_source_campaign: PhoneNumberLeadSourceCampaignResponse | None
    is_active: bool

    @model_validator(mode="after")
    def expose_effective_mms_capability(self) -> Self:
        self.mms_enabled = is_mms_capable(
            provider=self.provider,
            sms_enabled=self.sms_enabled,
            mms_enabled=self.mms_enabled,
        )
        return self


class InboundCallConfigRequest(BaseModel):
    """Workspace-managed AI-first routing configuration."""

    enabled: bool
    assigned_agent_id: uuid.UUID | None = None
    fallback_number: str | None = Field(default=None, max_length=30)
    transfer_destination_number: str | None = Field(default=None, max_length=30)

    @field_validator("fallback_number", "transfer_destination_number")
    @classmethod
    def normalize_destination(cls, value: str | None) -> str | None:
        """Store routing destinations in canonical E.164 format."""
        if value is None:
            return None
        try:
            return normalize_phone_e164(value)
        except PhoneNumberError as exc:
            raise ValueError("Enter a valid phone number") from exc

    @model_validator(mode="after")
    def require_activation_agent(self) -> Self:
        """Activation names its agent; existing encrypted destinations may be reused."""
        if self.enabled and self.assigned_agent_id is None:
            raise ValueError("Choose a voice agent before activation")
        return self


class InboundReadinessCheck(BaseModel):
    """One non-sensitive activation prerequisite."""

    code: str
    ready: bool
    message: str


class InboundCallReadinessResponse(BaseModel):
    """Inbound AI routing state and bounded readiness details."""

    phone_number_id: uuid.UUID
    ready: bool
    enabled: bool
    assigned_agent_id: uuid.UUID | None = None
    fallback_configured: bool
    transfer_destination_configured: bool
    checks: list[InboundReadinessCheck]


class PaginatedPhoneNumbers(BaseModel):
    """Paginated phone numbers response."""

    items: list[PhoneNumberResponse]
    total: int
    page: int
    page_size: int
    pages: int


class PhoneNumberUpdate(BaseModel):
    """Schema for updating a phone number."""

    friendly_name: str | None = None
    assigned_agent_id: uuid.UUID | None = None
    lead_source_id: uuid.UUID | None = None
    lead_source_campaign_id: uuid.UUID | None = None
    tracking_label: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class SearchPhoneNumbersRequest(BaseModel):
    """Search phone numbers request."""

    country: str = "US"
    area_code: str | None = None
    contains: str | None = None
    limit: int = 10


class PurchasePhoneNumberRequest(BaseModel):
    """Purchase phone number request."""

    phone_number: str


class PhoneNumberInfoResponse(BaseModel):
    """Phone number info from Telnyx."""

    id: str
    phone_number: str
    friendly_name: str | None
    capabilities: dict[str, bool] | None
