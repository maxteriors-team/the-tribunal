"""Ergonomic list-pagination helpers for API endpoints."""

from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.pagination import paginate


async def list_paginated(
    db: AsyncSession,
    query: Select[tuple[Any, ...]],
    *,
    page: int = 1,
    page_size: int = 50,
    unique: bool = False,
) -> dict[str, Any]:
    """Run a query with pagination and return a plain dict.

    Thin wrapper around :func:`app.db.pagination.paginate` that returns a
    dict ready to feed into a ``Paginated[T]`` Pydantic response model.
    Items are returned as raw ORM rows; callers are responsible for any
    per-item serialization (or can use ``PaginationResult.to_response``).

    Args:
        db: Async database session.
        query: SQLAlchemy select statement to paginate.
        page: 1-based page number.
        page_size: Number of items per page.
        unique: Call ``result.unique()`` before scalars — required for
            queries using ``joinedload``/``selectinload``.

    Returns:
        Dict with ``items``, ``total``, ``page``, ``page_size``, ``pages``.
    """
    result = await paginate(db, query, page=page, page_size=page_size, unique=unique)
    return {
        "items": list(result.items),
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "pages": result.pages,
    }
