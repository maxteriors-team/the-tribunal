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
async def test_workspace_wide_email_excludes_scoped_roles() -> None:
    db = _db_for_empty_result()

    await workspace_notification_email_users(db, uuid.uuid4())

    query = db.execute.await_args.args[0]
    role_values = next(
        value for key, value in query.compile().params.items() if key.startswith("role_")
    )
    assert set(role_values) == {"owner", "admin", "manager", "dispatcher"}
    assert WorkspaceRole.SALES_REP.value not in role_values


@pytest.mark.asyncio
async def test_targeted_email_can_reach_any_workspace_member() -> None:
    db = _db_for_empty_result()

    await workspace_notification_email_users(db, uuid.uuid4(), recipient_user_ids=[42])

    query = db.execute.await_args.args[0]
    params = query.compile().params
    assert not any(key.startswith("role_") for key in params)
    assert next(value for key, value in params.items() if key.startswith("id_")) == [42]
