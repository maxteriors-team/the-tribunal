"""Pagination utilities for SQLAlchemy async queries."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class PaginationResult[T]:
    """Result of a paginated query."""

    items: Sequence[T]
    total: int
    page: int
    page_size: int
    pages: int

    def to_response[R: BaseModel](self, response_model: type[R]) -> dict[str, Any]:
        """Convert to a paginated response dict compatible with Pydantic models.

        Args:
            response_model: Pydantic model class to validate each item with.

        Returns:
            Dict with items, total, page, page_size, pages keys.

        Example:
            result = await paginate(db, query, page=page, page_size=page_size)
            return PaginatedAgents(**result.to_response(AgentResponse))
        """
        return {
            "items": [response_model.model_validate(item) for item in self.items],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "pages": self.pages,
        }


async def paginate(
    db: AsyncSession,
    query: Select[tuple[Any, ...]],
    page: int = 1,
    page_size: int = 50,
    unique: bool = False,
) -> PaginationResult[Any]:
    """Execute a paginated query and return results with metadata.

    Args:
        db: Async database session.
        query: SQLAlchemy select statement to paginate.
        page: 1-based page number.
        page_size: Number of items per page.
        unique: Call result.unique() before scalars — required for queries
            that use joinedload/selectinload to avoid duplicate rows.
    """
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply pagination
    paginated_query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(paginated_query)
    items = (result.unique() if unique else result).scalars().all()

    # Calculate pages
    pages = (total + page_size - 1) // page_size if total > 0 else 1

    return PaginationResult(items=items, total=total, page=page, page_size=page_size, pages=pages)
