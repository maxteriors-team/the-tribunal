"""Tests for actionable-event notifications (push + email fan-out).

Covers the unified dispatcher :func:`notify_workspace_event` (push delivery,
email delivery, master-toggle and per-type preference gating) plus the firing
point in each originating service: reviews, deal coach at-risk alerts,
missed-call text-back, roleplay completion, and the automation worker.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import notifications
from app.services.notifications import notify_workspace_event

pytestmark = pytest.mark.asyncio


def _member(
    *,
    email: str | None = "op@example.com",
    notification_email: bool = True,
    pref_attr: str = "notification_push_reviews",
    pref_value: bool = True,
    user_id: int = 1,
) -> SimpleNamespace:
    user = SimpleNamespace(id=user_id, email=email, notification_email=notification_email)
    setattr(user, pref_attr, pref_value)
    return user


def _db_with_members(members: list[Any]) -> MagicMock:
    workspace = SimpleNamespace(id=uuid.uuid4(), name="Acme Co")
    scalars = MagicMock()
    scalars.all.return_value = members
    members_result = MagicMock()
    members_result.scalars.return_value = scalars

    db = MagicMock()
    db.get = AsyncMock(return_value=workspace)
    db.execute = AsyncMock(return_value=members_result)
    return db


def _patch_channels(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, AsyncMock]:
    push = MagicMock()
    push.send_to_workspace_members = AsyncMock(return_value=True)
    monkeypatch.setattr(notifications, "push_notification_service", push)
    email = AsyncMock(return_value=True)
    monkeypatch.setattr(notifications, "send_event_notification_email", email)
    return push.send_to_workspace_members, email


# --------------------------------------------------------------------------- #
# notify_workspace_event dispatcher
# --------------------------------------------------------------------------- #


async def test_dispatch_sends_push_and_email(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db_with_members([_member(user_id=1), _member(user_id=2)])
    push, email = _patch_channels(monkeypatch)

    result = await notify_workspace_event(
        db,
        workspace_id=str(uuid.uuid4()),
        notification_type="review",
        title="New review",
        body="A new review came in",
        email_subject="New review",
    )

    assert result.push_sent is True
    assert result.emails_sent == 2
    push.assert_awaited_once()
    assert push.await_args.kwargs["notification_type"] == "review"
    assert email.await_count == 2


async def test_dispatch_skips_email_without_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db_with_members([_member()])
    push, email = _patch_channels(monkeypatch)

    result = await notify_workspace_event(
        db,
        workspace_id=str(uuid.uuid4()),
        notification_type="review",
        title="t",
        body="b",
    )

    assert result.emails_sent == 0
    push.assert_awaited_once()
    email.assert_not_awaited()


async def test_dispatch_email_respects_master_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db_with_members([_member(notification_email=False)])
    _push, email = _patch_channels(monkeypatch)

    result = await notify_workspace_event(
        db,
        workspace_id=str(uuid.uuid4()),
        notification_type="review",
        title="t",
        body="b",
        email_subject="s",
    )

    assert result.emails_sent == 0
    email.assert_not_awaited()


async def test_dispatch_email_respects_per_type_pref(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db_with_members([_member(pref_attr="notification_push_reviews", pref_value=False)])
    _push, email = _patch_channels(monkeypatch)

    result = await notify_workspace_event(
        db,
        workspace_id=str(uuid.uuid4()),
        notification_type="review",
        title="t",
        body="b",
        email_subject="s",
    )

    assert result.emails_sent == 0
    email.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Per-service firing points
# --------------------------------------------------------------------------- #


async def test_review_service_fires_review_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.reviews.review_service import ReviewService

    spy = AsyncMock()
    monkeypatch.setattr(notifications, "notify_workspace_event", spy)

    svc = ReviewService.__new__(ReviewService)
    svc.db = MagicMock()
    svc.log = MagicMock()
    workspace = SimpleNamespace(id=uuid.uuid4(), name="Acme Co")

    await svc._notify_review(workspace=workspace, rating=5, is_positive=True, dedupe_key="rr-1")

    spy.assert_awaited_once()
    assert spy.await_args.kwargs["notification_type"] == "review"
    assert spy.await_args.kwargs["email_subject"] is not None
    assert spy.await_args.kwargs["dedupe_key"] == "rr-1"


async def test_deal_coach_fires_deal_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.opportunities.deal_coach_service import DealCoachService

    spy = AsyncMock()
    monkeypatch.setattr(notifications, "notify_workspace_event", spy)

    svc = DealCoachService.__new__(DealCoachService)
    svc.db = MagicMock()
    svc.log = MagicMock()
    card = SimpleNamespace(
        opportunity_id=uuid.uuid4(),
        name="Big Deal",
        deal_health="at_risk",
        health_score=40,
        top_risk="Champion silent 14 days",
        next_best_action=SimpleNamespace(title="Re-engage the champion"),
    )

    await svc._notify_at_risk_deal(workspace_id=uuid.uuid4(), card=card, dedupe_key="opp-1")

    spy.assert_awaited_once()
    assert spy.await_args.kwargs["notification_type"] == "deal_alert"
    assert spy.await_args.kwargs["dedupe_key"] == "opp-1"


async def test_missed_call_textback_fires_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.telephony.missed_call_textback import _notify_textback_sent

    spy = AsyncMock()
    monkeypatch.setattr(notifications, "notify_workspace_event", spy)

    workspace = SimpleNamespace(id=uuid.uuid4(), name="Acme Co")
    contact = SimpleNamespace(full_name="Dana Lee")
    log = MagicMock()

    await _notify_textback_sent(
        MagicMock(),
        workspace=workspace,
        contact=contact,
        contact_phone="+15551230000",
        body="Sorry we missed you",
        call_control_id="v3:call-1",
        log=log,
    )

    spy.assert_awaited_once()
    assert spy.await_args.kwargs["notification_type"] == "missed_call_textback"
    assert spy.await_args.kwargs["dedupe_key"] == "v3:call-1"


async def test_roleplay_fires_completion_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ai.roleplay.roleplay_service import RoleplayService

    spy = AsyncMock()
    monkeypatch.setattr(notifications, "notify_workspace_event", spy)

    svc = RoleplayService.__new__(RoleplayService)
    svc.db = MagicMock()
    run = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        agent_name="Closer Bot",
        persona_name="Skeptical CFO",
        overall_score=82,
    )

    await svc._notify_roleplay_completed(run)

    spy.assert_awaited_once()
    assert spy.await_args.kwargs["notification_type"] == "roleplay"
    assert spy.await_args.kwargs["dedupe_key"] == str(run.id)


async def test_automation_worker_fires_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers.automation_worker import AutomationWorker

    spy = AsyncMock()
    monkeypatch.setattr(notifications, "notify_workspace_event", spy)

    worker = AutomationWorker.__new__(AutomationWorker)
    worker.logger = MagicMock()
    automation = SimpleNamespace(
        id=uuid.uuid4(),
        name="Welcome flow",
        trigger_type="review_received",
        workspace_id=uuid.uuid4(),
    )
    contact = SimpleNamespace(full_name="Dana Lee", email=None, phone_number=None)
    execution = SimpleNamespace(id=uuid.uuid4())

    await worker._notify_automation_triggered(automation, contact, execution, MagicMock())

    spy.assert_awaited_once()
    assert spy.await_args.kwargs["notification_type"] == "automation"
    assert spy.await_args.kwargs["dedupe_key"] == str(execution.id)
