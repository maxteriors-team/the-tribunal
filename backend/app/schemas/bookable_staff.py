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


class BookableStaffLinkRequest(BaseModel):
    """Give a workspace member a booking calendar, or take it away.

    The Settings → Team form of the link. ``name``/``email`` seed the staff row
    the first time a member is made bookable; they are ignored once a row exists,
    so the toggle never overwrites a name someone edited in the agent's pool.
    """

    bookable: bool
    name: str = Field(min_length=1, max_length=200)
    email: str | None = None


class BookableStaffCreate(BaseModel):
    """Schema for creating a bookable staff member."""

    name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    skills: list[str] = []
    is_active: bool = True
    priority: int = 0
    user_id: int | None = Field(
        default=None,
        description=(
            "Workspace member this staff row belongs to. Setting it puts the "
            "bookings on that person's calendar, so it requires members:manage."
        ),
    )

    @field_validator("skills", mode="before")
    @classmethod
    def normalize_skills(cls, value: object) -> object:
        return _normalize_skills(value)


class BookableStaffUpdate(BaseModel):
    """Schema for updating a bookable staff member."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = None
    skills: list[str] | None = None
    is_active: bool | None = None
    priority: int | None = None
    user_id: int | None = Field(
        default=None,
        description=(
            "Workspace member this staff row belongs to; send null to unlink. "
            "Requires members:manage — the link decides whose calendar the "
            "bookings appear on."
        ),
    )

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
    user_id: int | None
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
