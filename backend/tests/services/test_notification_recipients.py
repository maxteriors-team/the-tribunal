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


@pytest.mark.asyncio
async def test_workspace_wide_email_only_includes_active_admin_roles() -> None:
    db = _db_for_empty_result()

    await workspace_notification_email_users(db, uuid.uuid4())

    query = db.execute.await_args.args[0]
    params = query.compile().params
    role_values = next(value for key, value in params.items() if key.startswith("role_"))
    assert set(role_values) == {"owner", "admin"}
    assert WorkspaceRole.MANAGER.value not in role_values
    assert WorkspaceRole.DISPATCHER.value not in role_values
    assert WorkspaceRole.SALES_REP.value not in role_values
    assert "users.is_active IS true" in str(query)


@pytest.mark.asyncio
async def test_targeted_operational_email_can_reach_any_active_workspace_member() -> None:
    db = _db_for_empty_result()

    await workspace_notification_email_users(db, uuid.uuid4(), recipient_user_ids=[42])

    query = db.execute.await_args.args[0]
    params = query.compile().params
    assert not any(key.startswith("role_") for key in params)
    assert next(value for key, value in params.items() if key.startswith("id_")) == [42]
    assert "users.is_active IS true" in str(query)
