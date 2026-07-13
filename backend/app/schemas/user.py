"""User schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """Schema for creating a user."""

    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str | None = None


class UserResponse(BaseModel):
    """Schema for user response."""

    id: int
    email: str
    full_name: str | None
    is_active: bool
    created_at: datetime


class UserWithWorkspace(UserResponse):
    """Schema for user response with workspace info."""

    default_workspace_id: str | None = None
    # True when the account must reset its password before using the app (set at
    # provisioning for admin-issued temporary passwords). The frontend gates on
    # this and routes to the change-password flow.
    must_change_password: bool = False


class Token(BaseModel):
    """Schema for JWT token response.

    The refresh_token is delivered via httpOnly cookie, not in the response body.
    """

    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Schema for JWT token payload."""

    sub: int | None = None


# Settings schemas
class UserProfileResponse(BaseModel):
    """Schema for user profile response."""

    id: int
    email: str
    full_name: str | None
    phone_number: str | None
    timezone: str
    avatar_url: str | None = None
    created_at: datetime


class UserProfileUpdate(BaseModel):
    """Schema for updating user profile."""

    full_name: str | None = None
    phone_number: str | None = None
    timezone: str | None = None
    avatar_url: str | None = Field(None, max_length=1024)


class NotificationSettings(BaseModel):
    """Schema for notification settings."""

    notification_email: bool
    notification_sms: bool
    notification_push: bool
    notification_push_calls: bool
    notification_push_messages: bool
    notification_push_voicemail: bool
    notification_push_appointments: bool
    notification_push_reviews: bool
    notification_push_deal_alerts: bool
    notification_push_missed_call_textback: bool
    notification_push_roleplay: bool
    notification_push_automations: bool
    notification_push_new_lead: bool


class NotificationSettingsUpdate(BaseModel):
    """Schema for updating notification settings."""

    notification_email: bool | None = None
    notification_sms: bool | None = None
    notification_push: bool | None = None
    notification_push_calls: bool | None = None
    notification_push_messages: bool | None = None
    notification_push_voicemail: bool | None = None
    notification_push_appointments: bool | None = None
    notification_push_reviews: bool | None = None
    notification_push_deal_alerts: bool | None = None
    notification_push_missed_call_textback: bool | None = None
    notification_push_roleplay: bool | None = None
    notification_push_automations: bool | None = None
    notification_push_new_lead: bool | None = None


class IntegrationStatus(BaseModel):
    """Schema for integration status."""

    integration_type: str
    is_connected: bool
    display_name: str
    description: str


class IntegrationsResponse(BaseModel):
    """Schema for workspace integrations response."""

    integrations: list[IntegrationStatus]


class TeamMemberResponse(BaseModel):
    """Schema for team member response."""

    id: int
    email: str
    full_name: str | None
    avatar_url: str | None = None
    role: str
    created_at: datetime


# Business Hours schemas
class DaySchedule(BaseModel):
    """Schema for a single day's schedule."""

    enabled: bool
    open: str
    close: str


class BusinessHoursSettings(BaseModel):
    """Schema for business hours settings."""

    is_24_7: bool = False
    schedule: dict[str, DaySchedule] = {}


class BusinessHoursUpdate(BaseModel):
    """Schema for updating business hours."""

    is_24_7: bool | None = None
    schedule: dict[str, DaySchedule] | None = None


# Call Forwarding schemas
class CallForwardingSettings(BaseModel):
    """Schema for call forwarding settings."""

    enabled: bool = False
    forward_to: str | None = None
    mode: str = "no_answer"


class CallForwardingUpdate(BaseModel):
    """Schema for updating call forwarding."""

    enabled: bool | None = None
    forward_to: str | None = None
    mode: str | None = None


# Change Password schema
class ChangePasswordRequest(BaseModel):
    """Schema for changing password."""

    current_password: str
    new_password: str = Field(..., min_length=8)
