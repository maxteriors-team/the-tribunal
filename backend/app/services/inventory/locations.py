"""Location resolution shared by the posting engine and the CRUD service.

Kept in its own module so :mod:`app.services.inventory.stock_service` and
:mod:`app.services.inventory.inventory_service` can both use it without
importing each other.

The important behaviour is **lazy creation**: an operator who has never opened
the settings screen can still receive stock, because the first movement creates
a ``"Main"`` warehouse for the workspace. Onboarding steps that exist only to
satisfy a foreign key are how inventory features go unused.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import assert_workspace_owned, select_workspace_owned
from app.models.inventory import InventoryLocation

DEFAULT_LOCATION_NAME = "Main"


async def get_default_location(
    db: AsyncSession, workspace_id: uuid.UUID
) -> InventoryLocation | None:
    """Return the workspace's fallback location, if one exists.

    Prefers an explicitly flagged default, then the oldest active location, so a
    workspace that renamed "Main" still resolves somewhere sensible.
    """
    flagged = (
        (
            await db.execute(
                select_workspace_owned(
                    InventoryLocation,
                    workspace_id,
                    InventoryLocation.is_default.is_(True),
                    InventoryLocation.is_active.is_(True),
                ).order_by(InventoryLocation.created_at.asc())
            )
        )
        .scalars()
        .first()
    )
    if flagged is not None:
        return flagged

    return (
        (
            await db.execute(
                select_workspace_owned(
                    InventoryLocation,
                    workspace_id,
                    InventoryLocation.is_active.is_(True),
                ).order_by(InventoryLocation.created_at.asc())
            )
        )
        .scalars()
        .first()
    )


async def ensure_default_location(db: AsyncSession, workspace_id: uuid.UUID) -> InventoryLocation:
    """Return the workspace's default location, creating ``"Main"`` if needed."""
    existing = await get_default_location(db, workspace_id)
    if existing is not None:
        return existing

    location = InventoryLocation(
        workspace_id=workspace_id,
        name=DEFAULT_LOCATION_NAME,
        kind="warehouse",
        is_active=True,
        is_default=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    try:
        # Savepoint, not a bare flush: a losing race must roll back only this
        # INSERT, never the caller's in-flight stock movement.
        async with db.begin_nested():
            db.add(location)
            await db.flush()
    except IntegrityError:
        # Two first-ever movements raced. The unique index on
        # ``(workspace_id, lower(name))`` decided the winner; adopt it.
        winner = (
            (
                await db.execute(
                    select_workspace_owned(
                        InventoryLocation,
                        workspace_id,
                        func.lower(InventoryLocation.name) == DEFAULT_LOCATION_NAME.lower(),
                    )
                )
            )
            .scalars()
            .first()
        )
        if winner is None:
            raise
        return winner
    return location


async def resolve_location(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    location_id: uuid.UUID | None,
) -> InventoryLocation:
    """Resolve a caller-supplied location id, or fall back to the default.

    A cross-workspace id raises a tenant-safe 404 (it must look identical to a
    missing row), never a 403 that would confirm the row exists elsewhere.
    """
    if location_id is None:
        return await ensure_default_location(db, workspace_id)
    return await assert_workspace_owned(
        db,
        InventoryLocation,
        location_id,
        workspace_id,
        detail="Inventory location not found",
    )
