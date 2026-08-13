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
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from app.models.automation_event import (
    EVENT_STATUS_PENDING,
    EVENT_STATUS_PROCESSED,
)
from app.services.automations.events import (
    AUTOMATION_EVENT_TRIGGERS,
    EVENT_APPOINTMENT_BOOKED,
    EVENT_DEAL_STAGE_CHANGED,
    EVENT_INVOICE_PAID,
    EVENT_INVOICE_SENT,
    EVENT_JOB_COMPLETED,
    EVENT_JOB_SCHEDULED,
    EVENT_KNOWLEDGE_DOCUMENT_UPLOADED,
    EVENT_LEAD_CREATED,
    EVENT_LEAD_QUALIFIED,
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
from app.services.outbound.delivery import (
    OutboundDeliveryChannel,
    OutboundDeliveryResult,
    OutboundDeliveryStatus,
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
    EVENT_LEAD_CREATED,
    EVENT_LEAD_QUALIFIED,
    EVENT_APPOINTMENT_BOOKED,
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
        # Resume state: the cursor the step walk starts from, the trigger
        # payload carried across a wait, and the loop budget.
        step_index=0,
        context={},
        resume_count=0,
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


async def test_render_template_applies_fallback_when_token_blank() -> None:
    """A blank {first_name} falls back to the configured default."""
    worker = AutomationWorker()
    contact = _contact()
    contact.first_name = None

    rendered = worker._render_template(
        "Hi {first_name}, it's Max.", contact, {}, {"first_name": "there"}
    )

    assert rendered == "Hi there, it's Max."


async def test_render_template_fallback_not_used_when_value_present() -> None:
    """A real first name wins over the fallback."""
    worker = AutomationWorker()
    contact = _contact()  # first_name == "Ada"

    rendered = worker._render_template(
        "Hi {first_name}, it's Max.", contact, {}, {"first_name": "there"}
    )

    assert rendered == "Hi Ada, it's Max."


async def test_action_send_sms_normalizes_raw_us_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raw US number like \"(248) 555-0123\" is sent as E.164, with fallback."""
    import app.workers.automation_worker as mod

    worker = AutomationWorker()
    contact = _contact()
    contact.first_name = None  # exercise the fallback path
    contact.phone_number = "(248) 555-0123"

    agent_id = uuid.uuid4()
    conversation = SimpleNamespace(assigned_agent_id=None, ai_enabled=False)
    message = SimpleNamespace(conversation_id=uuid.uuid4())
    delivered = OutboundDeliveryResult(
        channel=OutboundDeliveryChannel.SMS,
        status=OutboundDeliveryStatus.SENT,
        message=message,
    )
    deliver = AsyncMock(return_value=delivered)
    monkeypatch.setattr(mod.outbound_delivery_service, "deliver", deliver)
    worker._resolve_from_number = AsyncMock(return_value="+12485930266")  # type: ignore[method-assign]

    automation = _automation("lead_created", [])
    db = MagicMock()
    workspace = SimpleNamespace(settings={"timezone": "America/New_York"})
    db.get = AsyncMock(side_effect=[workspace, conversation])
    db.flush = AsyncMock()
    result = await worker._action_send_sms(
        automation,
        contact,
        {
            "message": "Hi {first_name}",
            "fallbacks": {"first_name": "there"},
            "require_consent": True,
            "agent_id": str(agent_id),
        },
        {},
        db,
    )

    deliver.assert_awaited_once()
    delivered_db, request = deliver.await_args.args
    assert delivered_db is db
    assert request.to == "+12485550123"
    assert request.body == "Hi there"
    assert request.contact is contact
    assert request.require_sms_consent is True
    assert request.action_type == "automation_sms"
    assert request.agent_id == agent_id
    assert result is delivered
    assert conversation.assigned_agent_id == agent_id
    assert conversation.ai_enabled is True
    db.flush.assert_awaited_once()


async def test_lead_created_advances_only_after_accepted_sms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first accepted outreach owns new -> contacted; blocked sends do not."""
    import app.workers.automation_worker as mod

    worker = AutomationWorker()
    _auto_gate(monkeypatch)
    transition = AsyncMock(return_value=True)
    monkeypatch.setattr(mod, "mark_contact_contacted", transition)
    accepted = OutboundDeliveryResult(
        channel=OutboundDeliveryChannel.SMS,
        status=OutboundDeliveryStatus.SENT,
    )
    worker._action_send_sms = AsyncMock(return_value=accepted)  # type: ignore[method-assign]
    automation = _automation("lead_created", [{"type": "send_sms", "config": {"message": "Hi"}}])
    contact = _contact()
    contact.status = "new"

    await worker._run_actions(automation, contact, {}, _execution(), MagicMock())
    transition.assert_awaited_once_with(ANY, contact)

    transition.reset_mock()
    contact.status = "qualified"
    await worker._run_actions(automation, contact, {}, _execution(), MagicMock())
    transition.assert_not_awaited()

    contact.status = "new"
    blocked = OutboundDeliveryResult(
        channel=OutboundDeliveryChannel.SMS,
        status=OutboundDeliveryStatus.BLOCKED,
    )
    worker._action_send_sms = AsyncMock(return_value=blocked)  # type: ignore[method-assign]
    await worker._run_actions(automation, contact, {}, _execution(), MagicMock())
    transition.assert_not_awaited()


async def test_event_execution_hard_stops_no_automation_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.workers.automation_worker as mod

    worker = AutomationWorker()
    monkeypatch.setattr(mod, "automation_suppressed", AsyncMock(return_value=True))
    automation = _automation("lead_created", [{"type": "send_sms", "config": {}}])
    event = SimpleNamespace(id=uuid.uuid4(), contact_id=44, payload={})
    db = MagicMock()
    db.execute = AsyncMock()

    await worker._execute_event_for_automation(automation, event, _contact(), db)

    db.execute.assert_not_awaited()
    db.add.assert_not_called()


async def test_action_send_sms_skips_unnormalizable_phone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unparseable phone is skipped cleanly (no send, no raise)."""
    import app.workers.automation_worker as mod

    worker = AutomationWorker()
    contact = _contact()
    contact.phone_number = "not-a-phone"

    deliver = AsyncMock()
    monkeypatch.setattr(mod.outbound_delivery_service, "deliver", deliver)
    worker._resolve_from_number = AsyncMock(return_value="+12485930266")  # type: ignore[method-assign]

    automation = _automation("lead_created", [])
    await worker._action_send_sms(
        automation, contact, {"message": "Hi {first_name}"}, {}, MagicMock()
    )

    deliver.assert_not_awaited()


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
