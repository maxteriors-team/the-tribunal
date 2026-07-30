"""Worker-level tests for the ``backlog_below_threshold`` condition trigger.

The decision maths lives in ``tests/services/automations/test_backlog_condition.py``.
This file proves the wiring that turns a decision into demand generation:

* a thin backlog runs the automation's actions once, with **no** contact (a
  condition is caused by the business, not a person);
* a healthy backlog and an unset crew capacity run nothing at all;
* the cooldown is enforced by the same ``last_triggered_at`` that
  ``_run_actions`` stamps — proven by running two poll cycles back-to-back
  through the real action runner and seeing exactly one fire;
* the condition trigger never reaches the contact-polling query;
* ``start_drip_campaign`` activates a reactivation drip, is workspace-scoped, and
  works with or without a contact.

All unit-level (mocked sessions), so they run in default ``make ci.backend``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.drip_campaign import DripCampaignStatus
from app.models.field_service import JobStatus
from app.schemas.automation import AUTOMATION_TRIGGER_TYPES
from app.schemas.reporting import BacklogReport
from app.services.automations.conditions import CONDITION_BACKLOG_BELOW_THRESHOLD
from app.services.reporting.capacity_service import JobFact, assemble_backlog
from app.workers.automation_worker import AutomationWorker

AS_OF = date(2026, 7, 30)
WEEKLY_CAPACITY = 40.0
CONFIG = {"threshold_weeks": 4.0, "cooldown_days": 14}


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _backlog(weeks: float | None) -> BacklogReport:
    """A real ``BacklogReport`` whose ``backlog_weeks`` is exactly ``weeks``.

    Built through the pure assembler rather than hand-constructed so the report
    the worker reads is shaped by the same code that serves the fuel gauge.
    ``None`` models a workspace that never entered a crew capacity.
    """
    if weeks is None:
        return assemble_backlog(
            [JobFact(status=JobStatus.UNSCHEDULED)],
            as_of=AS_OF,
            weekly_capacity_hours=None,
        )

    start = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    return assemble_backlog(
        [
            JobFact(
                status=JobStatus.SCHEDULED,
                scheduled_start=start,
                scheduled_end=start + timedelta(hours=weeks * WEEKLY_CAPACITY),
            )
        ],
        as_of=AS_OF,
        weekly_capacity_hours=WEEKLY_CAPACITY,
    )


def _patch_capacity(monkeypatch: pytest.MonkeyPatch, report: BacklogReport) -> AsyncMock:
    """Patch the worker's CapacityService; return its compute_backlog mock."""
    import app.workers.automation_worker as mod

    compute = AsyncMock(return_value=report)
    monkeypatch.setattr(
        mod, "CapacityService", MagicMock(return_value=MagicMock(compute_backlog=compute))
    )
    return compute


def _automation(
    *,
    trigger_type: str = CONDITION_BACKLOG_BELOW_THRESHOLD,
    actions: list[dict] | None = None,
    trigger_config: dict | None = None,
    last_triggered_at: datetime | None = None,
) -> MagicMock:
    automation = MagicMock()
    automation.id = uuid.uuid4()
    automation.workspace_id = uuid.uuid4()
    automation.name = "Dry pipeline -> reactivation drip"
    automation.trigger_type = trigger_type
    automation.trigger_config = dict(CONFIG if trigger_config is None else trigger_config)
    automation.actions = actions if actions is not None else []
    automation.last_triggered_at = last_triggered_at
    automation.last_evaluated_at = None
    return automation


def _db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    return db


def _contact() -> MagicMock:
    contact = MagicMock()
    contact.id = 4242
    contact.workspace_id = uuid.uuid4()
    contact.first_name = "Ada"
    contact.last_name = "Lovelace"
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


def _auto_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the approval gate so every action auto-executes (auto-restored)."""
    import app.workers.automation_worker as mod

    monkeypatch.setattr(
        mod.approval_gate_service,
        "check_and_execute_or_queue",
        AsyncMock(return_value=("auto", None)),
    )


# --------------------------------------------------------------------------- #
# Registration + polling isolation                                             #
# --------------------------------------------------------------------------- #


def test_trigger_is_accepted_by_the_api_schema() -> None:
    assert CONDITION_BACKLOG_BELOW_THRESHOLD in AUTOMATION_TRIGGER_TYPES


async def test_condition_trigger_is_not_evaluated_by_contact_polling() -> None:
    """The polling path must issue no contact query for a condition trigger."""
    worker = AutomationWorker()
    db = _db()

    contacts = await worker._get_trigger_contacts(
        _automation(), datetime(2026, 1, 1, tzinfo=UTC), db
    )

    assert contacts == []
    db.execute.assert_not_awaited()


async def test_evaluate_automation_routes_condition_triggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_evaluate_automation`` hands condition triggers to the condition path
    instead of matching contacts."""
    worker = AutomationWorker()
    worker._evaluate_backlog_condition = AsyncMock()  # type: ignore[method-assign]
    worker._get_trigger_contacts = AsyncMock(return_value=[])  # type: ignore[method-assign]

    await worker._evaluate_automation(_automation(), _db())

    worker._evaluate_backlog_condition.assert_awaited_once()
    worker._get_trigger_contacts.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Fire / skip                                                                  #
# --------------------------------------------------------------------------- #


async def test_fires_when_backlog_is_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = AutomationWorker()
    compute = _patch_capacity(monkeypatch, _backlog(1.5))
    worker._run_actions = AsyncMock()  # type: ignore[method-assign]
    automation = _automation()
    db = _db()

    await worker._evaluate_backlog_condition(automation, db)

    compute.assert_awaited_once_with(automation.workspace_id)
    worker._run_actions.assert_awaited_once()
    args = worker._run_actions.await_args.args
    # (automation, contact, payload, execution, db) — a condition has no contact.
    assert args[0] is automation
    assert args[1] is None
    assert args[2]["backlog_weeks"] == 1.5
    assert args[2]["threshold_weeks"] == 4.0
    # An execution row is written so the run is auditable like any other.
    db.add.assert_called_once()
    execution = db.add.call_args.args[0]
    assert execution.automation_id == automation.id
    assert execution.contact_id is None
    assert execution.event_id is None
    db.flush.assert_awaited_once()
    assert automation.last_evaluated_at is not None


async def test_does_not_fire_when_backlog_is_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = AutomationWorker()
    _patch_capacity(monkeypatch, _backlog(9.0))
    worker._run_actions = AsyncMock()  # type: ignore[method-assign]
    automation = _automation()
    db = _db()

    await worker._evaluate_backlog_condition(automation, db)

    worker._run_actions.assert_not_awaited()
    db.add.assert_not_called()
    # Still marked evaluated so the cycle is recorded.
    assert automation.last_evaluated_at is not None


async def test_skips_silently_when_capacity_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No crew capacity -> ``backlog_weeks is None`` -> no campaign fires.

    Without this guard every workspace that skipped the capacity setting would
    fire every campaign it owns on the first poll.
    """
    worker = AutomationWorker()
    report = _backlog(None)
    assert report.backlog_weeks is None
    _patch_capacity(monkeypatch, report)
    worker._run_actions = AsyncMock()  # type: ignore[method-assign]
    db = _db()

    await worker._evaluate_backlog_condition(_automation(), db)

    worker._run_actions.assert_not_awaited()
    db.add.assert_not_called()


async def test_respects_cooldown_after_a_recent_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = AutomationWorker()
    _patch_capacity(monkeypatch, _backlog(0.5))
    worker._run_actions = AsyncMock()  # type: ignore[method-assign]
    automation = _automation(last_triggered_at=datetime.now(UTC) - timedelta(days=2))

    await worker._evaluate_backlog_condition(automation, _db())

    worker._run_actions.assert_not_awaited()


async def test_fires_again_after_the_cooldown_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = AutomationWorker()
    _patch_capacity(monkeypatch, _backlog(0.5))
    worker._run_actions = AsyncMock()  # type: ignore[method-assign]
    automation = _automation(last_triggered_at=datetime.now(UTC) - timedelta(days=15))

    await worker._evaluate_backlog_condition(automation, _db())

    worker._run_actions.assert_awaited_once()


async def test_does_not_double_fire_across_consecutive_poll_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two cycles, one fire — through the *real* action runner.

    The worker polls every 60 seconds and a thin backlog stays thin for weeks, so
    the cooldown is only real if ``_run_actions`` actually stamps
    ``last_triggered_at``. This runs the genuine runner (with an empty action
    list) twice and asserts the second cycle is a no-op.
    """
    worker = AutomationWorker()
    _auto_gate(monkeypatch)
    _patch_capacity(monkeypatch, _backlog(0.75))
    notify = AsyncMock()
    worker._notify_automation_triggered = notify  # type: ignore[method-assign]
    automation = _automation(actions=[])
    db = _db()

    await worker._evaluate_backlog_condition(automation, db)
    first_fire = automation.last_triggered_at
    assert first_fire is not None  # the cooldown clock actually started

    await worker._evaluate_backlog_condition(automation, db)

    assert notify.await_count == 1
    assert db.add.call_count == 1  # only the first cycle wrote an execution
    assert automation.last_triggered_at == first_fire


# --------------------------------------------------------------------------- #
# start_drip_campaign action                                                   #
# --------------------------------------------------------------------------- #


async def test_run_actions_dispatches_start_drip_campaign_without_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting a drip is workspace-level, so it runs for a contactless trigger."""
    worker = AutomationWorker()
    _auto_gate(monkeypatch)
    worker._action_start_drip_campaign = AsyncMock()  # type: ignore[method-assign]
    worker._notify_automation_triggered = AsyncMock()  # type: ignore[method-assign]
    automation = _automation(
        actions=[{"type": "start_drip_campaign", "config": {"drip_campaign_id": str(uuid.uuid4())}}]
    )
    execution = _execution()

    await worker._run_actions(automation, None, {}, execution, _db())

    worker._action_start_drip_campaign.assert_awaited_once()
    assert execution.status == "completed"


@pytest.mark.parametrize("config", [{}, {"drip_campaign_id": ""}, {"drip_campaign_id": "nope"}])
async def test_start_drip_skips_missing_or_invalid_campaign_id(config: dict) -> None:
    worker = AutomationWorker()
    db = _db()

    await worker._action_start_drip_campaign(_automation(), None, config, db)

    db.execute.assert_not_awaited()  # bailed before any query


async def test_start_drip_skips_campaign_outside_the_workspace() -> None:
    worker = AutomationWorker()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = _db()
    db.execute = AsyncMock(return_value=result)

    await worker._action_start_drip_campaign(
        _automation(), None, {"drip_campaign_id": str(uuid.uuid4())}, db
    )

    db.execute.assert_awaited_once()


async def test_start_drip_activates_a_draft_campaign() -> None:
    worker = AutomationWorker()
    campaign = MagicMock(status=DripCampaignStatus.DRAFT, started_at=None)
    result = MagicMock()
    result.scalar_one_or_none.return_value = campaign
    db = _db()
    db.execute = AsyncMock(return_value=result)

    await worker._action_start_drip_campaign(
        _automation(), None, {"drip_campaign_id": str(uuid.uuid4())}, db
    )

    assert campaign.status == DripCampaignStatus.ACTIVE
    assert campaign.started_at is not None


async def test_start_drip_leaves_an_active_campaign_alone() -> None:
    """Re-firing must not reset ``started_at`` on a running sequence."""
    worker = AutomationWorker()
    started = datetime(2026, 7, 1, tzinfo=UTC)
    campaign = MagicMock(status=DripCampaignStatus.ACTIVE, started_at=started)
    result = MagicMock()
    result.scalar_one_or_none.return_value = campaign
    db = _db()
    db.execute = AsyncMock(return_value=result)

    await worker._action_start_drip_campaign(
        _automation(), None, {"drip_campaign_id": str(uuid.uuid4())}, db
    )

    assert campaign.status == DripCampaignStatus.ACTIVE
    assert campaign.started_at == started


async def test_start_drip_refuses_a_completed_campaign() -> None:
    """Mirrors the API's rule: a finished sequence is not resurrected."""
    worker = AutomationWorker()
    campaign = MagicMock(status=DripCampaignStatus.COMPLETED, started_at=None)
    result = MagicMock()
    result.scalar_one_or_none.return_value = campaign
    db = _db()
    db.execute = AsyncMock(return_value=result)

    await worker._action_start_drip_campaign(
        _automation(), None, {"drip_campaign_id": str(uuid.uuid4())}, db
    )

    assert campaign.status == DripCampaignStatus.COMPLETED


async def test_start_drip_enrolls_the_matched_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    """A contact-bearing trigger (e.g. never_booked) also enrolls the contact."""
    import app.workers.automation_worker as mod

    enroll = AsyncMock(return_value=1)
    monkeypatch.setattr(mod, "enroll_contacts", enroll)

    worker = AutomationWorker()
    campaign = MagicMock(status=DripCampaignStatus.PAUSED, started_at=None)
    result = MagicMock()
    result.scalar_one_or_none.return_value = campaign
    db = _db()
    db.execute = AsyncMock(return_value=result)
    contact = _contact()

    await worker._action_start_drip_campaign(
        _automation(), contact, {"drip_campaign_id": str(uuid.uuid4())}, db
    )

    enroll.assert_awaited_once()
    assert enroll.await_args.args[1] == [contact.id]
    assert campaign.status == DripCampaignStatus.ACTIVE


async def test_start_drip_can_skip_enrollment(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.workers.automation_worker as mod

    enroll = AsyncMock(return_value=0)
    monkeypatch.setattr(mod, "enroll_contacts", enroll)

    worker = AutomationWorker()
    campaign = MagicMock(status=DripCampaignStatus.ACTIVE, started_at=datetime.now(UTC))
    result = MagicMock()
    result.scalar_one_or_none.return_value = campaign
    db = _db()
    db.execute = AsyncMock(return_value=result)

    await worker._action_start_drip_campaign(
        _automation(),
        _contact(),
        {"drip_campaign_id": str(uuid.uuid4()), "enroll_contact": False},
        db,
    )

    enroll.assert_not_awaited()
