"""Google Calendar integration API schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr


class GoogleCalendarStatus(BaseModel):
    configured: bool
    connected: bool
    google_email: EmailStr | None = None
    calendar_id: str | None = None
    connected_at: datetime | None = None


class GoogleCalendarAuthorizeRequest(BaseModel):
    return_url: str | None = None


class GoogleCalendarAuthorizeResponse(BaseModel):
    authorization_url: str
