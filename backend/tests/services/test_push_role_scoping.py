"""Workspace-wide push must respect the notification audience.

``send_to_workspace_members`` used to select every membership row with no role
filter, so a field technician's phone buzzed for every deposit a customer paid.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.roles import WorkspaceRole
from app.services.push_notifications import PushNotificationService

pytestmark = pytest.mark.asyncio

# (user_id, role) rows as returned by the membership select.
MEMBERSHIPS = [
    (1, WorkspaceRole.OWNER.value),
    (2, WorkspaceRole.SALES_REP.value),
    (3, WorkspaceRole.TECHNICIAN.value),
    (4, WorkspaceRole.LEAD_TECHNICIAN.value),
    (5, WorkspaceRole.MANAGER.value),
]


def _db() -> MagicMock:
    result = MagicMock()
    result.all.return_value = MEMBERSHIPS
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


async def _push_targets(monkeypatch: pytest.MonkeyPatch, notification_type: str) -> set[int]:
    service = PushNotificationService()
    targeted: set[int] = set()

    async def fake_send_to_user(db, user_id, *args, **kwargs):  # noqa: ANN001, ANN202
        targeted.add(user_id)
        return True

    monkeypatch.setattr(service, "send_to_user", fake_send_to_user)
    await service.send_to_workspace_members(
        db=_db(),
        workspace_id=str(uuid.uuid4()),
        title="Payment Received",
        body="500.00 USD collected",
        notification_type=notification_type,
    )
    return targeted


async def test_deposit_push_skips_the_crew(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = await _push_targets(monkeypatch, "payment")

    assert 3 not in targets, "field technician was pushed a customer deposit"
    assert 4 not in targets, "lead technician was pushed a customer deposit"
    assert targets == {1, 2, 5}


async def test_job_assignment_push_reaches_the_crew(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = await _push_targets(monkeypatch, "job_assignment")

    assert {3, 4} <= targets


async def test_untyped_push_fails_closed_to_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PushNotificationService()
    targeted: set[int] = set()

    async def fake_send_to_user(db, user_id, *args, **kwargs):  # noqa: ANN001, ANN202
        targeted.add(user_id)
        return True

    monkeypatch.setattr(service, "send_to_user", fake_send_to_user)
    await service.send_to_workspace_members(
        db=_db(), workspace_id=str(uuid.uuid4()), title="t", body="b"
    )

    assert targeted == {1}


async def test_returns_false_when_audience_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """No eligible role means no send and no crash."""
    service = PushNotificationService()
    result = MagicMock()
    result.all.return_value = [(3, WorkspaceRole.TECHNICIAN.value)]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(service, "send_to_user", AsyncMock(return_value=True))

    sent = await service.send_to_workspace_members(
        db=db,
        workspace_id=str(uuid.uuid4()),
        title="Payment Received",
        body="b",
        notification_type="payment",
    )

    assert sent is False
    service.send_to_user.assert_not_awaited()


async def test_one_failing_recipient_does_not_stop_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PushNotificationService()
    reached: list[int] = []

    async def flaky(db, user_id, *args, **kwargs):  # noqa: ANN001, ANN202
        if user_id == 1:
            raise RuntimeError("expo down")
        reached.append(user_id)
        return True

    monkeypatch.setattr(service, "send_to_user", flaky)
    sent = await service.send_to_workspace_members(
        db=_db(),
        workspace_id=str(uuid.uuid4()),
        title="t",
        body="b",
        notification_type="payment",
    )

    assert sent is True
    assert reached == [2, 5]
