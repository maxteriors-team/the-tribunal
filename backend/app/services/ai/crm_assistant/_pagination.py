"""Truthful result envelopes for CRM assistant list tools.

Every list tool used to return ``{"count": len(rows)}`` after capping the
query at ``limit``. With 300 matching Smiths and a default limit of 10, the
model was told ``count: 10`` and confidently answered "you have 10". The count
described the page, not the world, and nothing in the payload said so.

``listing()`` reports all three facts separately:

- ``returned``  — rows in this payload
- ``total``     — rows matching the filter, from a real ``COUNT(*)``
- ``has_more``  — whether the answer is truncated

Tool descriptions can then tell the model to trust ``total`` for "how many"
questions and to raise ``limit`` when ``has_more`` is true.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


async def count_matching(
    db: AsyncSession,
    model: type[DeclarativeBase],
    stmt: Select[Any],
) -> int:
    """Count every row matching ``stmt``'s filters, ignoring paging clauses.

    ``order_by``/``limit``/``offset`` are stripped so the count describes the
    full result set rather than the page. Pass the same filtered statement used
    for the fetch so the two can never drift apart.
    """

    count_stmt = (
        stmt.order_by(None)
        .limit(None)
        .offset(None)
        .with_only_columns(func.count())
        .select_from(model)
    )
    total = await db.scalar(count_stmt)
    return int(total) if total is not None else 0


def listing(
    items: list[Any],
    *,
    total: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the standard list-tool envelope.

    ``total`` is authoritative for "how many" questions; ``returned`` only
    describes this payload.
    """

    returned = len(items)
    payload: dict[str, Any] = {
        "success": True,
        "data": items,
        "returned": returned,
        "total": total,
        "has_more": total > returned,
    }
    if extra:
        payload.update(extra)
    return payload


def local_listing(items: list[Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Envelope for lists already computed in full in memory (no COUNT needed)."""

    return listing(items, total=len(items), extra=extra)
