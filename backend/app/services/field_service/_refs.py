"""Shared tenant-scoped lookup and cross-entity reference validation.

These helpers keep every field-service operation inside one workspace. They use
:func:`app.db.scope.get_workspace_owned` (which returns ``None`` for missing or
cross-tenant rows) and raise typed field-service domain errors — never
``HTTPException`` — so the service layer stays framework-agnostic.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.db.scope import get_workspace_owned
from app.models.contact import Contact
from app.models.field_service import Crew
from app.models.workspace import WorkspaceMembership
from app.services.exceptions import ServiceError
from app.services.field_service.exceptions import (
    ContactNotInWorkspaceError,
    CrewNotFoundError,
    UserNotMemberError,
)


async def get_owned_or_raise[ModelT: DeclarativeBase](
    db: AsyncSession,
    model: type[ModelT],
    model_id: uuid.UUID | int,
    workspace_id: uuid.UUID,
    not_found: ServiceError,
) -> ModelT:
    """Fetch a workspace-owned row or raise ``not_found``.

    Cross-workspace rows are indistinguishable from missing ones, so a tenant
    can never probe another tenant's id space.
    """
    row = await get_workspace_owned(db, model, model_id, workspace_id)
    if row is None:
        raise not_found
    return row


async def assert_contact_in_workspace(
    db: AsyncSession, contact_id: int, workspace_id: uuid.UUID
) -> None:
    """Ensure ``contact_id`` belongs to ``workspace_id``."""
    if await get_workspace_owned(db, Contact, contact_id, workspace_id) is None:
        raise ContactNotInWorkspaceError()


async def assert_crew_in_workspace(
    db: AsyncSession, crew_id: uuid.UUID, workspace_id: uuid.UUID
) -> None:
    """Ensure ``crew_id`` belongs to ``workspace_id`` before assigning it."""
    if await get_workspace_owned(db, Crew, crew_id, workspace_id) is None:
        raise CrewNotFoundError()


async def assert_user_is_member(db: AsyncSession, user_id: int, workspace_id: uuid.UUID) -> None:
    """Ensure ``user_id`` is a member of ``workspace_id`` before linking a login."""
    result = await db.execute(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise UserNotMemberError()
