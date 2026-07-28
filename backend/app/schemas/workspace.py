"""Workspace schemas."""

import typing
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.roles import AssignableRole


class WorkspaceCreate(BaseModel):
    """Schema for creating a workspace."""

    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: str | None = None
    settings: dict[str, typing.Any] = Field(default_factory=dict)


class WorkspaceUpdate(BaseModel):
    """Schema for updating a workspace."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    settings: dict[str, typing.Any] | None = None


class WorkspaceResponse(BaseModel):
    """Schema for workspace response."""

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    settings: dict[str, typing.Any]
    is_active: bool
    # ``None`` until the operator finishes the onboarding wizard. This is the
    # only "is this workspace configured?" signal clients may use — counting
    # seeded rows (default agent/pipeline) reports configured at creation time.
    onboarding_completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # The caller's role in this workspace, populated on per-workspace reads so
    # the frontend can role-gate UI without a second request. ``None`` on
    # responses where membership context is not resolved (e.g. create).
    role: str | None = None

    model_config = {"from_attributes": True}


class WorkspaceMembershipResponse(BaseModel):
    """Schema for workspace membership response."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: int
    role: str
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceWithMembership(BaseModel):
    """Schema for workspace with membership info."""

    workspace: WorkspaceResponse
    role: str
    is_default: bool


class UpdateMemberRoleRequest(BaseModel):
    """Request to update a member's role."""

    role: AssignableRole


class MemberResponse(BaseModel):
    """Response for member operations."""

    user_id: int
    role: str
    message: str
