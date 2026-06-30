"""Unit tests for the event-based automation trigger plumbing.

These run in default CI (no ``integration`` marker) using mocked sessions. They
cover, per new trigger:

* event triggers are NOT evaluated by the contact-polling path;
* the worker drains a queued event and dispatches the right action;
* contact-targeting actions are skipped when an event has no contact;
* per-(automation, event) dedupe prevents double execution on re-drain.

End-to-end DB-backed coverage (real services emitting + worker executing) lives
in ``tests/workers/test_automation_events_integration.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.automation_event import (
    EVENT_STATUS_PENDING,
    EVENT_STATUS_PROCESSED,
)
from app.services.automations.events import (
    AUTOMATION_EVENT_TRIGGERS,
    EVENT_DEAL_STAGE_CHANGED,
    EVENT_INVOICE_PAID,
    EVENT_INVOICE_SENT,
    EVENT_JOB_COMPLETED,
    EVENT_JOB_SCHEDULED,
    EVENT_KNOWLEDGE_DOCUMENT_UPLOADED,
    EVENT_MISSED_CALL,
    EVENT_OPPORTUNITY_CREATED,
    EVENT_QUOTE_APPROVED,
    EVENT_QUOTE_CONVERTED,
    EVENT_QUOTE_DECLINED,
    EVENT_QUOTE_SENT,
    EVENT_REVIEW_RECEIVED,
    EVENT_REVIEW_REQUEST_RESPONSE,
    EVENT_ROLEPLAY_COMPLETED,
)
from app.workers.automation_worker import AutomationWorker

ALL_EVENT_TRIGGERS = [
    EVENT_REVIEW_RECEIVED,
    EVENT_REVIEW_REQUEST_RESPONSE,
    EVENT_OPPORTUNITY_CREATED,
    EVENT_DEAL_STAGE_CHANGED,
    EVENT_MISSED_CALL,
    EVENT_ROLEPLAY_COMPLETED,
    EVENT_KNOWLEDGE_DOCUMENT_UPLOADED,
    EVENT_QUOTE_SENT,
    EVENT_QUOTE_APPROVED,
    EVENT_QUOTE_DECLINED,
    EVENT_QUOTE_CONVERTED,
    EVENT_INVOICE_SENT,
    EVENT_INVOICE_PAID,
    EVENT_JOB_SCHEDULED,
    EVENT_JOB_COMPLETED,
]


def _auto_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the approval gate so every action auto-executes (auto-restored)."""
    import app.workers.automation_worker as mod

    monkeypatch.setattr(
        mod.approval_gate_service,
        "check_and_execute_or_queue",
        AsyncMock(return_value=("auto", None)),
    )


def _automation(trigger_type: str, actions: list[dict]) -> MagicMock:
    automation = MagicMock()
    automation.id = uuid.uuid4()
    automation.workspace_id = uuid.uuid4()
    automation.name = "Test automation"
    automation.trigger_type = trigger_type
    automation.actions = actions
    automation.last_triggered_at = None
    return automation


def _contact() -> MagicMock:
    contact = MagicMock()
    contact.id = 123
    contact.workspace_id = uuid.uuid4()
    contact.first_name = "Ada"
    contact.last_name = "Lovelace"
    contact.company_name = "Analytical"
    contact.email = "ada@example.com"
    contact.phone_number = "+15551230000"
    return contact


def _execution() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status="pending",
        scheduled_for=None,
        executed_at=None,
        error=None,
    )


def test_all_new_triggers_are_registered() -> None:
    """Every new trigger constant is in the worker's event-trigger set."""
    for trigger in ALL_EVENT_TRIGGERS:
        assert trigger in AUTOMATION_EVENT_TRIGGERS


@pytest.mark.parametrize("trigger", ALL_EVENT_TRIGGERS)
async def test_event_trigger_not_evaluated_by_polling(trigger: str) -> None:
    """Event triggers must return no contacts from the polling path."""
    worker = AutomationWorker()
    automation = _automation(trigger, actions=[])
    db = MagicMock()
    db.execute = AsyncMock()

    contacts = await worker._get_trigger_contacts(automation, datetime(2026, 1, 1, tzinfo=UTC), db)

    assert contacts == []
    # No query should be issued for an event trigger (handled by event drain).
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("action_type", "method_name"),
    [
        ("send_sms", "_action_send_sms"),
        ("send_email", "_action_send_email"),
        ("make_call", "_action_make_call"),
        ("enroll_campaign", "_action_enroll_campaign"),
        ("apply_tag", "_action_apply_tag"),
        ("add_tag", "_action_apply_tag"),
    ],
)
async def test_run_actions_dispatches_each_action(
    action_type: str, method_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each action type routes to its handler when a contact is present."""
    worker = AutomationWorker()
    _auto_gate(monkeypatch)
    setattr(worker, method_name, AsyncMock())

    automation = _automation("review_received", [{"type": action_type, "config": {}}])
    contact = _contact()
    execution = _execution()
    db = MagicMock()

    await worker._run_actions(automation, contact, {}, execution, db)

    getattr(worker, method_name).assert_awaited_once()
    assert execution.status == "completed"


@pytest.mark.parametrize(
    "action_type", ["send_sms", "send_email", "make_call", "enroll_campaign", "apply_tag"]
)
async def test_contact_actions_skipped_without_contact(
    action_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contact-targeting actions are skipped (not run) for contactless events."""
    worker = AutomationWorker()
    _auto_gate(monkeypatch)
    # Spy on every action method to prove none are invoked.
    for name in (
        "_action_send_sms",
        "_action_send_email",
        "_action_make_call",
        "_action_enroll_campaign",
        "_action_apply_tag",
    ):
        setattr(worker, name, AsyncMock())

    automation = _automation("roleplay_completed", [{"type": action_type, "config": {}}])
    execution = _execution()
    db = MagicMock()

    await worker._run_actions(automation, None, {}, execution, db)

    for name in (
        "_action_send_sms",
        "_action_send_email",
        "_action_make_call",
        "_action_enroll_campaign",
        "_action_apply_tag",
    ):
        getattr(worker, name).assert_not_awaited()
    # Execution still completes (no error) even though the action was skipped.
    assert execution.status == "completed"


async def test_render_template_uses_event_payload() -> None:
    """Event payload tokens (e.g. {rating}) render alongside contact tokens."""
    worker = AutomationWorker()
    contact = _contact()

    rendered = worker._render_template(
        "Hi {first_name}, thanks for the {rating}-star review!",
        contact,
        {"rating": 5},
    )

    assert rendered == "Hi Ada, thanks for the 5-star review!"


async def test_process_event_dedupes_existing_execution() -> None:
    """A second drain of the same event does not re-run an automation."""
    worker = AutomationWorker()
    automation = _automation("missed_call", [{"type": "apply_tag", "config": {}}])

    # db.execute(...).first() -> truthy means an execution already exists.
    existing_result = MagicMock()
    existing_result.first.return_value = (uuid.uuid4(),)
    db = MagicMock()
    db.execute = AsyncMock(return_value=existing_result)
    db.add = MagicMock()
    db.flush = AsyncMock()

    event = SimpleNamespace(id=uuid.uuid4(), contact_id=None, payload={})

    await worker._execute_event_for_automation(automation, event, None, db)

    # No execution row added and no flush -> deduped.
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


def test_event_status_constants() -> None:
    assert EVENT_STATUS_PENDING == "pending"
    assert EVENT_STATUS_PROCESSED == "processed"
