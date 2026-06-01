"""Pagination utilities for SQLAlchemy async queries."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, overload

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

type ResponseBuilder[T] = Callable[..., T]
RowMapper = Callable[[Any], Any]


def list_response(items: Sequence[Any], total: int | None = None) -> dict[str, Any]:
    """Return the standard non-paginated list response payload."""
    materialized = list(items)
    return {"items": materialized, "total": len(materialized) if total is None else total}


@dataclass
class PaginationResult[T]:
    """Result of a paginated query."""

    items: Sequence[T]
    total: int
    page: int
    page_size: int
    pages: int

    def to_dict(self, items: Sequence[Any] | None = None) -> dict[str, Any]:
        """Return a standard paginated response payload."""
        return {
            "items": list(self.items if items is None else items),
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "pages": self.pages,
        }

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
        return self.to_dict([response_model.model_validate(item) for item in self.items])

    @overload
    def build_response[R: BaseModel](
        self,
        *,
        item_model: type[R] | None = None,
        item_mapper: RowMapper | None = None,
        response_builder: None = None,
    ) -> dict[str, Any]: ...

    @overload
    def build_response[R: BaseModel, PageT](
        self,
        *,
        item_model: type[R] | None = None,
        item_mapper: RowMapper | None = None,
        response_builder: ResponseBuilder[PageT],
    ) -> PageT: ...

    def build_response[R: BaseModel, PageT](
        self,
        *,
        item_model: type[R] | None = None,
        item_mapper: RowMapper | None = None,
        response_builder: ResponseBuilder[PageT] | None = None,
    ) -> dict[str, Any] | PageT:
        """Build a paginated response with one shared metadata shape.

        ``item_mapper`` is useful for joined row tuples whose response model is
        not a direct validation of the scalar ORM row. ``response_builder`` is
        typically a Pydantic model class such as ``PaginatedOpportunities``.
        """
        if item_mapper is not None:
            items = [item_mapper(item) for item in self.items]
        elif item_model is not None:
            items = [item_model.model_validate(item) for item in self.items]
        else:
            items = list(self.items)

        payload = self.to_dict(items)
        if response_builder is None:
            return payload
        return response_builder(**payload)


async def paginate(
    db: AsyncSession,
    query: Select[tuple[Any, ...]],
    page: int = 1,
    page_size: int = 50,
    unique: bool = False,
    item_mapper: RowMapper | None = None,
) -> PaginationResult[Any]:
    """Execute a paginated query and return results with metadata.

    Args:
        db: Async database session.
        query: SQLAlchemy select statement to paginate.
        page: 1-based page number.
        page_size: Number of items per page.
        unique: Call result.unique() before scalars — required for queries
            that use joinedload/selectinload to avoid duplicate rows.
        item_mapper: Optional mapper applied to each scalar item before the
            result is returned.
    """
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply pagination
    paginated_query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(paginated_query)
    scalar_items = (result.unique() if unique else result).scalars().all()
    items = (
        [item_mapper(item) for item in scalar_items] if item_mapper is not None else scalar_items
    )

    # Calculate pages
    pages = (total + page_size - 1) // page_size if total > 0 else 1

    return PaginationResult(items=items, total=total, page=page, page_size=page_size, pages=pages)


async def paginate_rows(
    db: AsyncSession,
    query: Select[tuple[Any, ...]],
    page: int = 1,
    page_size: int = 50,
    row_mapper: RowMapper | None = None,
) -> PaginationResult[Any]:
    """Paginate a query whose result rows are tuples rather than scalars."""
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = (await db.execute(count_query)).scalar() or 0

    paginated_query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(paginated_query)
    rows = result.all()
    items = [row_mapper(row) for row in rows] if row_mapper is not None else rows
    pages = (total + page_size - 1) // page_size if total > 0 else 1

    return PaginationResult(items=items, total=total, page=page, page_size=page_size, pages=pages)
