"""Bookable staff schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_skills(value: object) -> object:
    """Trim, drop empties, and de-duplicate skill tags (case-insensitive)."""
    if not isinstance(value, list):
        return value
    seen: set[str] = set()
    out: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        tag = raw.strip()
        key = tag.casefold()
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)
    return out


class BookableStaffCreate(BaseModel):
    """Schema for creating a bookable staff member."""

    name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    calcom_event_type_id: int | None = None
    skills: list[str] = []
    is_active: bool = True
    priority: int = 0

    @field_validator("skills", mode="before")
    @classmethod
    def normalize_skills(cls, value: object) -> object:
        return _normalize_skills(value)


class BookableStaffUpdate(BaseModel):
    """Schema for updating a bookable staff member."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = None
    calcom_event_type_id: int | None = None
    skills: list[str] | None = None
    is_active: bool | None = None
    priority: int | None = None

    @field_validator("skills", mode="before")
    @classmethod
    def normalize_skills(cls, value: object) -> object:
        if value is None:
            return None
        return _normalize_skills(value)


class BookableStaffResponse(BaseModel):
    """Bookable staff response schema."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID | None
    name: str
    email: str | None
    calcom_event_type_id: int | None
    skills: list[str]
    is_active: bool
    priority: int
    assignment_count: int
    last_assigned_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BookableStaffList(BaseModel):
    """List of bookable staff for an agent."""

    items: list[BookableStaffResponse]
    total: int
