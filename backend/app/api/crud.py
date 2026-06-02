"""Generic CRUD helper functions for API endpoints."""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.scope import assert_workspace_owned

type IdType = uuid.UUID | int


async def get_or_404[ModelT: Base](
    db: AsyncSession,
    model: type[ModelT],
    id: IdType,
    *,
    workspace_id: uuid.UUID | None = None,
    detail: str | None = None,
    options: list[Any] | None = None,
) -> ModelT:
    """Fetch a model instance by ID, raising 404 if not found.

    Args:
        db: Database session
        model: SQLAlchemy model class
        id: Primary key value
        workspace_id: Optional workspace filter for multi-tenant models
        detail: Custom error message (defaults to "{ModelName} not found")
        options: SQLAlchemy query options (e.g., selectinload, joinedload)

    Returns:
        The model instance

    Raises:
        HTTPException: 404 if not found
    """
    if workspace_id is not None:
        return await assert_workspace_owned(
            db,
            model,
            id,
            workspace_id,
            detail=detail,
            options=options,
        )

    query = select(model).where(model.id == id)  # type: ignore[attr-defined]

    if options:
        for opt in options:
            query = query.options(opt)

    result = await db.execute(query)
    instance = result.scalar_one_or_none()

    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail or f"{model.__name__} not found",
        )

    return instance


async def get_nested_or_404[ModelT: Base](
    db: AsyncSession,
    model: type[ModelT],
    id: IdType,
    *,
    parent_field: str,
    parent_id: IdType,
    detail: str | None = None,
    options: list[Any] | None = None,
) -> ModelT:
    """Fetch a nested model by ID and parent ID (e.g., Stage -> Pipeline).

    Args:
        db: Database session
        model: SQLAlchemy model class
        id: Primary key value
        parent_field: Name of the foreign key field on the model
        parent_id: Parent's primary key value
        detail: Custom error message (defaults to "{ModelName} not found")
        options: SQLAlchemy query options (e.g., selectinload, joinedload)

    Returns:
        The model instance

    Raises:
        HTTPException: 404 if not found
    """
    query = select(model).where(
        model.id == id,  # type: ignore[attr-defined]
        getattr(model, parent_field) == parent_id,
    )

    if options:
        for opt in options:
            query = query.options(opt)

    result = await db.execute(query)
    instance = result.scalar_one_or_none()

    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail or f"{model.__name__} not found",
        )

    return instance
