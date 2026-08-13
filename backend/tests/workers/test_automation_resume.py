"""Multi-step workflows: waiting, resuming, branching and loop bounds.

Before resume existed, ``wait`` set ``status='scheduled'`` and returned, and
nothing ever read that status back — so every step after a wait was silently
dropped and no multi-step drip could work at all. The first class here is the
regression test for exactly that, and the rest cover what resuming makes
reachable: state surviving the gap, and the budgets that stop a goto loop.

Unit layer (mocked sessions) — the cursor logic and the resume guards. The
end-to-end proof against real Postgres lives in the integration tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.automations.runner import MAX_RESUMES, MAX_STEPS_PER_RUN
from app.workers.automation_worker import AutomationWorker

pytestmark = pytest.mark.asyncio


def _auto_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the approval gate so every action auto-executes (auto-restored)."""
    import app.workers.automation_worker as mod

    monkeypatch.setattr(
        mod.approval_gate_service,
        "check_and_execute_or_queue",
        AsyncMock(return_value=("auto", None)),
    )


def _automation(actions: list[dict]) -> MagicMock:
    automation = MagicMock()
    automation.id = uuid.uuid4()
    automation.workspace_id = uuid.uuid4()
    automation.name = "Drip"
    automation.trigger_type = "review_received"
    automation.actions = actions
    automation.is_active = True
    automation.last_triggered_at = None
    return automation


def _contact() -> MagicMock:
    contact = MagicMock()
    contact.id = 123
    contact.first_name = "Ada"
    contact.last_name = "Lovelace"
    contact.email = "ada@example.com"
    contact.phone_number = "+15551230000"
    return contact


def _execution(**overrides) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "automation_id": uuid.uuid4(),
        "contact_id": 123,
        "status": "pending",
        "scheduled_for": None,
        "executed_at": None,
        "error": None,
        "step_index": 0,
        "context": {},
        "resume_count": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _worker(monkeypatch: pytest.MonkeyPatch) -> AutomationWorker:
    _auto_gate(monkeypatch)
    worker = AutomationWorker()
    # Notification is a side channel; silence it so assertions stay on the walk.
    monkeypatch.setattr(worker, "_notify_automation_triggered", AsyncMock())
    return worker


class TestWaitParksTheRun:
    """The regression class: a wait must suspend, not silently truncate."""

    async def test_steps_before_the_wait_run_and_the_run_is_parked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worker = _worker(monkeypatch)
        sms = AsyncMock()
        monkeypatch.setattr(worker, "_action_send_sms", sms)

        automation = _automation(
            [
                {"type": "send_sms", "config": {"message": "first"}},
                {"type": "wait", "config": {"days": 2}},
                {"type": "send_sms", "config": {"message": "second"}},
            ]
        )
        execution = _execution()

        await worker._run_actions(automation, _contact(), {}, execution, AsyncMock())

        assert sms.await_count == 1
        assert execution.status == "scheduled"
        # Cursor points *past* the wait, or the resume re-serves the same delay.
        assert execution.step_index == 2
        assert execution.scheduled_for is not None

    async def test_wait_is_not_marked_completed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A parked run marked 'completed' would never be picked back up."""
        worker = _worker(monkeypatch)
        monkeypatch.setattr(worker, "_action_send_sms", AsyncMock())

        execution = _execution()
        await worker._run_actions(
            _automation([{"type": "wait", "config": {"hours": 1}}, {"type": "send_sms"}]),
            _contact(),
            {},
            execution,
            AsyncMock(),
        )

        assert execution.status == "scheduled"
        assert execution.executed_at is None

    async def test_scheduled_time_reflects_the_configured_delay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worker = _worker(monkeypatch)
        execution = _execution()

        before = datetime.now(UTC)
        await worker._run_actions(
            _automation([{"type": "wait", "config": {"days": 3}}]),
            _contact(),
            {},
            execution,
            AsyncMock(),
        )

        delay = execution.scheduled_for - before
        assert timedelta(days=3) - timedelta(minutes=1) < delay < timedelta(days=3, minutes=1)

    async def test_zero_wait_does_not_park_the_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worker = _worker(monkeypatch)
        sms = AsyncMock()
        monkeypatch.setattr(worker, "_action_send_sms", sms)

        execution = _execution()
        await worker._run_actions(
            _automation(
                [{"type": "wait", "config": {"hours": 0}}, {"type": "send_sms"}],
            ),
            _contact(),
            {},
            execution,
            AsyncMock(),
        )

        assert execution.status == "completed"
        assert sms.await_count == 1


class TestResumingFromTheCursor:
    async def test_resume_runs_only_the_remaining_steps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The half before the wait must not be re-sent to the customer."""
        worker = _worker(monkeypatch)
        sms = AsyncMock()
        monkeypatch.setattr(worker, "_action_send_sms", sms)

        automation = _automation(
            [
                {"type": "send_sms", "config": {"message": "first"}},
                {"type": "wait", "config": {"days": 2}},
                {"type": "send_sms", "config": {"message": "second"}},
            ]
        )
        # Re-entering where the wait left off.
        execution = _execution(step_index=2, status="pending")

        await worker._run_actions(automation, _contact(), {}, execution, AsyncMock())

        assert sms.await_count == 1
        assert sms.await_args.args[2] == {"message": "second"}
        assert execution.status == "completed"

    async def test_trigger_payload_survives_the_wait(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tokens like {rating} must not render blank after a resume."""
        worker = _worker(monkeypatch)
        sms = AsyncMock()
        monkeypatch.setattr(worker, "_action_send_sms", sms)

        execution = _execution()
        await worker._run_actions(
            _automation([{"type": "wait", "config": {"days": 1}}, {"type": "send_sms"}]),
            _contact(),
            {"rating": 5},
            execution,
            AsyncMock(),
        )
        assert execution.context == {"rating": 5}

        # Resume carries the persisted context back in.
        await worker._run_actions(
            _automation([{"type": "wait", "config": {"days": 1}}, {"type": "send_sms"}]),
            _contact(),
            execution.context,
            execution,
            AsyncMock(),
        )
        assert sms.await_args.args[3] == {"rating": 5}

    async def test_cursor_past_a_shortened_workflow_completes_cleanly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An operator may delete steps while a customer is parked mid-run."""
        worker = _worker(monkeypatch)
        execution = _execution(step_index=9)

        await worker._run_actions(
            _automation([{"type": "send_sms"}]), _contact(), {}, execution, AsyncMock()
        )

        assert execution.status == "completed"


class TestResumeGuards:
    async def test_paused_automation_abandons_the_parked_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pausing mid-wait must not still deliver the back half of a sequence."""
        worker = _worker(monkeypatch)
        automation = _automation([{"type": "send_sms"}])
        automation.is_active = False

        db = AsyncMock()
        db.get = AsyncMock(return_value=automation)
        execution = _execution(status="scheduled")

        await worker._resume_execution(execution, db)

        assert execution.status == "failed"
        assert execution.scheduled_for is None

    async def test_deleted_automation_abandons_the_parked_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worker = _worker(monkeypatch)
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        execution = _execution(status="scheduled")

        await worker._resume_execution(execution, db)

        assert execution.status == "failed"

    async def test_resume_budget_stops_a_loop_hiding_behind_a_wait(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worker = _worker(monkeypatch)
        db = AsyncMock()
        execution = _execution(status="scheduled", resume_count=MAX_RESUMES)

        await worker._resume_execution(execution, db)

        assert execution.status == "failed"
        assert "loop" in (execution.error or "")
        assert execution.scheduled_for is None


class TestLoopBounds:
    async def test_backward_goto_loop_fails_within_one_cycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A branch cycling with no wait must be caught inside one poll."""
        worker = _worker(monkeypatch)
        monkeypatch.setattr(worker, "_action_send_sms", AsyncMock())
        # Every contact matches, so the branch always jumps backwards.
        monkeypatch.setattr(
            "app.workers.automation_worker.contact_matches_rules",
            AsyncMock(return_value=True),
        )

        automation = _automation(
            [
                {"id": "top", "type": "send_sms", "config": {"message": "loop"}},
                {
                    "type": "branch",
                    "config": {
                        "conditions": [{"field": "lead_score", "operator": "gte", "value": 1}],
                        "then_goto": "top",
                    },
                },
            ]
        )
        execution = _execution()

        await worker._run_actions(automation, _contact(), {}, execution, AsyncMock())

        assert execution.status == "failed"
        assert str(MAX_STEPS_PER_RUN) in (execution.error or "")
