"""Phone number schemas for phone number management endpoints."""

import uuid

from pydantic import BaseModel, ConfigDict


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
    is_active: bool


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
