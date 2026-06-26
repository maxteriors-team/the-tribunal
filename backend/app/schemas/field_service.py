"""Schemas for field-service entities: service locations, crews, technicians."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


# --------------------------------------------------------------------------- #
# Service locations
# --------------------------------------------------------------------------- #
class ServiceLocationCreate(BaseModel):
    """Create a service location (job site) for a customer."""

    contact_id: int = Field(..., description="Owning customer contact id")
    name: str | None = Field(None, max_length=200)
    address_line1: str | None = Field(None, max_length=500)
    address_line2: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=200)
    state: str | None = Field(None, max_length=200)
    postal_code: str | None = Field(None, max_length=50)
    country: str = Field(default="US", min_length=2, max_length=2)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    access_notes: str | None = Field(None, max_length=2000)
    is_active: bool = True


class ServiceLocationUpdate(BaseModel):
    """Partial update for a service location."""

    name: str | None = Field(None, max_length=200)
    address_line1: str | None = Field(None, max_length=500)
    address_line2: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=200)
    state: str | None = Field(None, max_length=200)
    postal_code: str | None = Field(None, max_length=50)
    country: str | None = Field(None, min_length=2, max_length=2)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    access_notes: str | None = Field(None, max_length=2000)
    is_active: bool | None = None


class ServiceLocationResponse(BaseModel):
    """Service location response."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    contact_id: int
    name: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str
    latitude: float | None
    longitude: float | None
    access_notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ServiceLocationListResponse(BaseModel):
    """List of service locations."""

    items: list[ServiceLocationResponse]
    total: int


# --------------------------------------------------------------------------- #
# Crews
# --------------------------------------------------------------------------- #
class CrewCreate(BaseModel):
    """Create a field crew."""

    name: str = Field(..., min_length=1, max_length=200)
    color: str = Field(default="#6366f1", pattern=HEX_COLOR)
    description: str | None = Field(None, max_length=2000)
    is_active: bool = True


class CrewUpdate(BaseModel):
    """Partial update for a crew."""

    name: str | None = Field(None, min_length=1, max_length=200)
    color: str | None = Field(None, pattern=HEX_COLOR)
    description: str | None = Field(None, max_length=2000)
    is_active: bool | None = None


class CrewResponse(BaseModel):
    """Crew response."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    color: str
    description: str | None
    is_active: bool
    technician_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CrewListResponse(BaseModel):
    """List of crews."""

    items: list[CrewResponse]
    total: int


# --------------------------------------------------------------------------- #
# Technicians
# --------------------------------------------------------------------------- #
class TechnicianCreate(BaseModel):
    """Create a technician."""

    name: str = Field(..., min_length=1, max_length=200)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    skills: list[str] = Field(default_factory=list)
    crew_id: uuid.UUID | None = None
    user_id: int | None = None
    color: str = Field(default="#0ea5e9", pattern=HEX_COLOR)
    is_active: bool = True


class TechnicianUpdate(BaseModel):
    """Partial update for a technician."""

    name: str | None = Field(None, min_length=1, max_length=200)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    skills: list[str] | None = None
    crew_id: uuid.UUID | None = None
    user_id: int | None = None
    color: str | None = Field(None, pattern=HEX_COLOR)
    is_active: bool | None = None


class TechnicianResponse(BaseModel):
    """Technician response."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: int | None
    crew_id: uuid.UUID | None
    name: str
    email: str | None
    phone: str | None
    skills: list[str]
    color: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TechnicianListResponse(BaseModel):
    """List of technicians."""

    items: list[TechnicianResponse]
    total: int
