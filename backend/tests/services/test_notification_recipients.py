"""Recipient policy tests for operator notification emails."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.roles import WorkspaceRole
from app.services.notification_recipients import workspace_notification_email_users


def _db_for_empty_result() -> AsyncMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = result
    return db


def _role_values(db: AsyncMock) -> list[str]:
    query = db.execute.await_args.args[0]
    params = query.compile().params
    return next(value for key, value in params.items() if key.startswith("role_"))


@pytest.mark.asyncio
async def test_untyped_email_stays_admin_only() -> None:
    """A caller that does not declare its event cannot widen its own audience."""
    db = _db_for_empty_result()

    await workspace_notification_email_users(db, uuid.uuid4())

    assert set(_role_values(db)) == {"owner", "admin"}
    assert "users.is_active IS true" in str(db.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_payment_email_reaches_sales_but_not_the_crew() -> None:
    db = _db_for_empty_result()

    await workspace_notification_email_users(db, uuid.uuid4(), notification_type="payment")

    role_values = set(_role_values(db))
    assert WorkspaceRole.SALES_REP.value in role_values
    assert WorkspaceRole.MANAGER.value in role_values
    assert WorkspaceRole.TECHNICIAN.value not in role_values
    assert WorkspaceRole.LEAD_TECHNICIAN.value not in role_values


@pytest.mark.asyncio
async def test_back_office_email_excludes_sales() -> None:
    db = _db_for_empty_result()

    await workspace_notification_email_users(db, uuid.uuid4(), notification_type="review")

    role_values = set(_role_values(db))
    assert WorkspaceRole.MANAGER.value in role_values
    assert WorkspaceRole.SALES_REP.value not in role_values


@pytest.mark.asyncio
async def test_targeted_operational_email_can_reach_any_active_workspace_member() -> None:
    db = _db_for_empty_result()

    await workspace_notification_email_users(db, uuid.uuid4(), recipient_user_ids=[42])

    query = db.execute.await_args.args[0]
    params = query.compile().params
    assert not any(key.startswith("role_") for key in params)
    assert next(value for key, value in params.items() if key.startswith("id_")) == [42]
    assert "users.is_active IS true" in str(query)
