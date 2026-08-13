"""Workspace-level Team controls for bookable staff resources."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.bookable_staff import BookableStaff
from app.services.calendar.bookable_staff_service import BookableStaffService


class _ScalarRows:
    def __init__(self, rows: list[BookableStaff]) -> None:
        self.rows = rows

    def scalars(self) -> _ScalarRows:
        return self

    def all(self) -> list[BookableStaff]:
        return self.rows


@pytest.mark.asyncio
async def test_disable_member_deactivates_every_pool_without_unlinking() -> None:
    """One Team toggle covers every agent pool and preserves booking history."""
    workspace_id = uuid.uuid4()
    user_id = 42
    rows = [
        BookableStaff(
            workspace_id=workspace_id,
            agent_id=uuid.uuid4(),
            user_id=user_id,
            name="Estimate pool",
            is_active=True,
        ),
        BookableStaff(
            workspace_id=workspace_id,
            agent_id=uuid.uuid4(),
            user_id=user_id,
            name="Service pool",
            is_active=True,
        ),
    ]
    db = AsyncMock()
    db.execute.return_value = _ScalarRows(rows)

    with patch(
        "app.services.calendar.bookable_staff_service.assert_user_is_member",
        new=AsyncMock(),
    ) as assert_member:
        result = await BookableStaffService(db).set_member_bookable(
            workspace_id,
            user_id,
            bookable=False,
            name="Terry Tech",
        )

    assert result is rows[0]
    assert all(staff.is_active is False for staff in rows)
    assert all(staff.user_id == user_id for staff in rows)
    assert_member.assert_awaited_once_with(db, user_id, workspace_id)
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(rows[0])


@pytest.mark.asyncio
async def test_enable_unlinked_member_creates_shared_workspace_resource() -> None:
    """A new Team booking toggle creates a resource every agent may route to."""
    workspace_id = uuid.uuid4()
    user_id = 42
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = _ScalarRows([])

    # AsyncMock cannot automatically emulate SQLAlchemy assigning defaults, but
    # the service only needs commit/refresh to complete for this behavior test.
    with patch(
        "app.services.calendar.bookable_staff_service.assert_user_is_member",
        new=AsyncMock(),
    ):
        result = await BookableStaffService(db).set_member_bookable(
            workspace_id,
            user_id,
            bookable=True,
            name="Terry Tech",
            email="terry@example.com",
        )

    assert result is not None
    assert result.workspace_id == workspace_id
    assert result.agent_id is None
    assert result.user_id == user_id
    assert result.is_active is True
    db.add.assert_called_once_with(result)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_disable_unlinked_member_is_idempotent() -> None:
    """Turning off a member with no resource is a successful no-op."""
    db: Any = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = _ScalarRows([])

    with patch(
        "app.services.calendar.bookable_staff_service.assert_user_is_member",
        new=AsyncMock(),
    ):
        result = await BookableStaffService(db).set_member_bookable(
            uuid.uuid4(),
            42,
            bookable=False,
            name="Terry Tech",
        )

    assert result is None
    db.commit.assert_not_awaited()
