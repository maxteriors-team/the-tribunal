"""Workspace-scoping helpers for tenant-isolated queries.

Every workspace-owned ORM model declares a ``workspace_id`` column. Endpoints
historically hand-roll ``where(Model.workspace_id == workspace_id)`` on every
list, get, update, and delete query. That repetition is a tenancy-leak risk:
one missed ``where`` clause exposes cross-workspace data.

:func:`apply_workspace_scope` centralizes that predicate. The helper validates
at runtime that the model actually carries a ``workspace_id`` column — so a
typo or accidental use on a non-tenant model fails loudly at import-time test
coverage rather than silently returning unscoped rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

_WORKSPACE_COLUMN = "workspace_id"
_ID_COLUMN = "id"

type IdType = uuid.UUID | int


def _require_column(model: type[DeclarativeBase], column_name: str) -> Any:
    """Return a mapped column or fail loudly for non-conforming models."""
    table = getattr(model, "__table__", None)
    if table is None or column_name not in table.columns:
        raise TypeError(
            f"{model.__name__} has no '{column_name}' column; "
            "workspace ownership helpers cannot be used on this model."
        )
    return table.columns[column_name]


def apply_workspace_scope[SelectT: Select](  # type: ignore[type-arg]
    query: SelectT,
    model: type[DeclarativeBase],
    workspace_id: uuid.UUID,
) -> SelectT:
    """Append a ``Model.workspace_id == workspace_id`` predicate to ``query``.

    Args:
        query: SQLAlchemy ``Select`` statement to constrain.
        model: ORM model class that must declare a ``workspace_id`` column.
        workspace_id: The workspace UUID to scope rows to.

    Returns:
        A new ``Select`` with the workspace predicate appended. The original
        ``query`` is left unmodified (SQLAlchemy ``Select`` is immutable).

    Raises:
        TypeError: If ``model`` does not declare a ``workspace_id`` column.
            Treating this as a programmer error — surfacing it loudly is the
            whole point of the helper.
    """
    column = _require_column(model, _WORKSPACE_COLUMN)
    return query.where(column == workspace_id)


def select_workspace_owned[ModelT: DeclarativeBase](
    model: type[ModelT],
    workspace_id: uuid.UUID,
    *criteria: Any,
    options: Sequence[Any] | None = None,
) -> Select[tuple[ModelT]]:
    """Build a ``SELECT`` for rows owned by ``workspace_id``.

    ``criteria`` are appended after the workspace predicate so callers can add
    model-specific filters without ever forgetting the tenant boundary.
    """
    query = apply_workspace_scope(select(model), model, workspace_id)
    if criteria:
        query = query.where(*criteria)
    if options:
        for option in options:
            query = query.options(option)
    return query


async def get_workspace_owned[ModelT: DeclarativeBase](
    db: AsyncSession,
    model: type[ModelT],
    model_id: IdType,
    workspace_id: uuid.UUID,
    *criteria: Any,
    options: Sequence[Any] | None = None,
) -> ModelT | None:
    """Fetch one workspace-owned model by primary key, returning ``None`` if absent."""
    id_column = _require_column(model, _ID_COLUMN)
    result = await db.execute(
        select_workspace_owned(
            model,
            workspace_id,
            id_column == model_id,
            *criteria,
            options=options,
        )
    )
    return result.scalar_one_or_none()


async def assert_workspace_owned[ModelT: DeclarativeBase](
    db: AsyncSession,
    model: type[ModelT],
    model_id: IdType,
    workspace_id: uuid.UUID,
    *criteria: Any,
    detail: str | None = None,
    options: Sequence[Any] | None = None,
) -> ModelT:
    """Fetch a workspace-owned row or raise a tenant-safe 404.

    Cross-workspace rows intentionally look identical to missing rows at API
    boundaries to avoid leaking object existence across tenants.
    """
    instance = await get_workspace_owned(
        db,
        model,
        model_id,
        workspace_id,
        *criteria,
        options=options,
    )
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail or f"{model.__name__} not found",
        )
    return instance
