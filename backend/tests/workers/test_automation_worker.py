"""Tests for the ``move_to_stage`` automation action.

Two layers:

* **Unit** (default CI, mocked sessions) — dispatch wiring, opportunity
  resolution order, validation/skip branches, and contact-only deal creation.
* **Integration** (``-m integration``, real Postgres) — an ``opportunity_created``
  event advances a deal, a ``lead_created`` event creates the contact's missing
  pipeline opportunity, moves are idempotent, and foreign stages are skipped.

The unit layer runs in ``make ci.backend`` (which excludes ``integration``); the
integration layer is the end-to-end proof, run with ``pytest -m integration``.
"""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.automation import AUTOMATION_ACTION_TYPES, AUTOMATION_CONTROL_FLOW_ACTIONS
from app.workers import automation_worker

_BRANCH_STEP = automation_worker._BRANCH_STEP
_WAIT_STEPS = automation_worker._WAIT_STEPS
AutomationWorker = automation_worker.AutomationWorker

# --------------------------------------------------------------------------- #
# Action-type parity                                                           #
# --------------------------------------------------------------------------- #


def test_declared_action_types_match_what_the_worker_dispatches() -> None:
    """``AUTOMATION_ACTION_TYPES`` feeds the CRM assistant tool enum.

    If the worker gains or drops a branch without updating the constant, the
    assistant would offer the model an action that silently does nothing, or
    hide one that works. This keeps the single source of truth honest.
    """
    # Side-effecting actions are dispatched in ``_execute_step``. Control-flow
    # steps never reach it — they move the cursor in ``_run_actions`` and are
    # matched against module-level constants, so they are checked separately.
    source = inspect.getsource(AutomationWorker._execute_step)

    for action_type in AUTOMATION_ACTION_TYPES:
        if action_type in AUTOMATION_CONTROL_FLOW_ACTIONS:
            continue
        assert f'"{action_type}"' in source, f"{action_type} is declared but never dispatched"


def test_control_flow_actions_are_handled_by_the_cursor_loop() -> None:
    """The step loop must recognise every declared control-flow step.

    An unrecognised control-flow step would fall through to the dispatch table
    and be logged as an unknown action — so a ``wait`` would stop delaying and
    the whole sequence would fire at once.
    """
    handled = set(_WAIT_STEPS) | {_BRANCH_STEP}
    assert handled == set(AUTOMATION_CONTROL_FLOW_ACTIONS)


# --------------------------------------------------------------------------- #
# Unit helpers                                                                 #
# --------------------------------------------------------------------------- #


def _auto_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the approval gate so every action auto-executes (auto-restored)."""
    monkeypatch.setattr(
        automation_worker.approval_gate_service,
        "check_and_execute_or_queue",
        AsyncMock(return_value=("auto", None)),
    )


def _automation(trigger_type: str, actions: list[dict]) -> MagicMock:
    automation = MagicMock()
    automation.id = uuid.uuid4()
    automation.workspace_id = uuid.uuid4()
    automation.name = "Move automation"
    automation.trigger_type = trigger_type
    automation.actions = actions
    automation.last_triggered_at = None
    return automation


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
        # Resume state: the cursor the step walk starts from, the trigger
        # payload carried across a wait, and the loop budget.
        step_index=0,
        context={},
        resume_count=0,
    )


def _patch_service(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch the lazily-imported OpportunityService; return its move_stage mock."""
    import app.services.opportunities.opportunity_service as opp_mod

    move_stage = AsyncMock(return_value=None)
    service = MagicMock()
    service.move_stage = move_stage
    monkeypatch.setattr(opp_mod, "OpportunityService", MagicMock(return_value=service))
    return move_stage


# --------------------------------------------------------------------------- #
# Unit: dispatch wiring + uuid helper                                          #
# --------------------------------------------------------------------------- #


def test_parse_uuid_handles_valid_empty_and_invalid() -> None:
    valid = uuid.uuid4()
    assert AutomationWorker._parse_uuid(str(valid)) == valid
    assert AutomationWorker._parse_uuid("  " + str(valid) + "  ") == valid
    assert AutomationWorker._parse_uuid("") is None
    assert AutomationWorker._parse_uuid(None) is None
    assert AutomationWorker._parse_uuid("not-a-uuid") is None


async def test_run_actions_dispatches_move_to_stage_without_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """move_to_stage is not a contact-action: it dispatches even with no contact
    (the event path can carry an opportunity_id alone)."""
    worker = AutomationWorker()
    _auto_gate(monkeypatch)
    worker._action_move_to_stage = AsyncMock()  # type: ignore[method-assign]

    automation = _automation(
        "deal_stage_changed",
        [{"type": "move_to_stage", "config": {"stage_id": str(uuid.uuid4())}}],
    )
    execution = _execution()

    await worker._run_actions(
        automation, None, {"opportunity_id": str(uuid.uuid4())}, execution, MagicMock()
    )

    worker._action_move_to_stage.assert_awaited_once()
    assert execution.status == "completed"


# --------------------------------------------------------------------------- #
# Unit: opportunity resolution order                                           #
# --------------------------------------------------------------------------- #


async def test_resolve_prefers_payload_opportunity_id() -> None:
    worker = AutomationWorker()
    automation = _automation("deal_stage_changed", [])
    oid = uuid.uuid4()

    result = MagicMock()
    result.scalar_one_or_none.return_value = oid
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    resolved = await worker._resolve_move_opportunity(
        automation, None, {"opportunity_id": str(oid)}, None, db
    )

    assert resolved == oid
    db.execute.assert_awaited_once()  # only the payload lookup ran


async def test_resolve_falls_back_to_contact_when_no_payload_id() -> None:
    worker = AutomationWorker()
    automation = _automation("contact_tagged", [])
    contact = _contact()
    oid = uuid.uuid4()

    result = MagicMock()
    result.scalar_one_or_none.return_value = oid
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    resolved = await worker._resolve_move_opportunity(automation, contact, {}, None, db)

    assert resolved == oid
    db.execute.assert_awaited_once()  # straight to the contact lookup


async def test_resolve_payload_miss_falls_back_to_contact() -> None:
    """A payload opportunity_id that doesn't resolve falls through to the contact."""
    worker = AutomationWorker()
    automation = _automation("deal_stage_changed", [])
    contact = _contact()
    oid = uuid.uuid4()

    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    hit = MagicMock()
    hit.scalar_one_or_none.return_value = oid
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[miss, hit])

    resolved = await worker._resolve_move_opportunity(
        automation, contact, {"opportunity_id": str(uuid.uuid4())}, None, db
    )

    assert resolved == oid
    assert db.execute.await_count == 2


async def test_resolve_returns_none_without_contact_or_payload() -> None:
    worker = AutomationWorker()
    automation = _automation("deal_stage_changed", [])
    db = MagicMock()
    db.execute = AsyncMock()

    resolved = await worker._resolve_move_opportunity(automation, None, {}, None, db)

    assert resolved is None
    db.execute.assert_not_awaited()  # no id and no contact -> no query


# --------------------------------------------------------------------------- #
# Unit: validation / skip branches of _action_move_to_stage                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("config", [{}, {"stage_id": ""}, {"stage_id": "not-a-uuid"}])
async def test_action_skips_missing_or_invalid_stage_id(
    config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = AutomationWorker()
    move_stage = _patch_service(monkeypatch)
    automation = _automation("deal_stage_changed", [])
    db = MagicMock()
    db.execute = AsyncMock()

    await worker._action_move_to_stage(automation, None, config, {}, db)

    db.execute.assert_not_awaited()  # bailed before any query
    move_stage.assert_not_awaited()


async def test_action_skips_stage_not_in_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = AutomationWorker()
    move_stage = _patch_service(monkeypatch)
    automation = _automation("deal_stage_changed", [])

    stage_check = MagicMock()
    stage_check.scalar_one_or_none.return_value = None  # stage not found in workspace
    db = MagicMock()
    db.execute = AsyncMock(return_value=stage_check)

    await worker._action_move_to_stage(
        automation, None, {"stage_id": str(uuid.uuid4())}, {"opportunity_id": str(uuid.uuid4())}, db
    )

    db.execute.assert_awaited_once()  # only the workspace stage check ran
    move_stage.assert_not_awaited()


async def test_action_happy_path_invokes_move_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = AutomationWorker()
    move_stage = _patch_service(monkeypatch)
    automation = _automation("deal_stage_changed", [])
    stage_id = uuid.uuid4()
    oid = uuid.uuid4()

    stage_check = MagicMock()
    pipeline_id = uuid.uuid4()
    stage_check.scalar_one_or_none.return_value = SimpleNamespace(
        id=stage_id, pipeline_id=pipeline_id, name="Qualified", probability=40
    )
    resolve = MagicMock()
    resolve.scalar_one_or_none.return_value = oid
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[stage_check, resolve])

    await worker._action_move_to_stage(
        automation, None, {"stage_id": str(stage_id)}, {"opportunity_id": str(oid)}, db
    )

    move_stage.assert_awaited_once()
    args, kwargs = move_stage.await_args
    assert args[0] == automation.workspace_id
    assert args[1] == oid
    assert args[2] == stage_id
    assert kwargs["user_id"] is None
    assert kwargs["source"] == "automation"
    assert kwargs["emit_event"] is False


async def test_action_creates_open_opportunity_when_contact_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = AutomationWorker()
    move_stage = _patch_service(monkeypatch)
    automation = _automation("lead_created", [])
    contact = _contact()
    contact.workspace_id = automation.workspace_id
    contact.company_name = ""
    contact.source = "lead_form"
    stage_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    target_stage = SimpleNamespace(
        id=stage_id, pipeline_id=pipeline_id, name="New Leads", probability=10
    )

    stage_check = MagicMock()
    stage_check.scalar_one_or_none.return_value = target_stage
    no_opportunity = MagicMock()
    no_opportunity.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[stage_check, no_opportunity])
    db.flush = AsyncMock()

    snapshot = MagicMock()
    monkeypatch.setattr(automation_worker, "snapshot_contact_attribution_on_opportunity", snapshot)

    await worker._action_move_to_stage(
        automation,
        contact,
        {"stage_id": str(stage_id), "pipeline_id": str(pipeline_id)},
        {},
        db,
    )

    created = db.add.call_args.args[0]
    assert created.workspace_id == automation.workspace_id
    assert created.pipeline_id == pipeline_id
    assert created.stage_id == stage_id
    assert created.primary_contact_id == contact.id
    assert created.status == "open"
    assert created.source == "lead_form"
    snapshot.assert_called_once_with(created, contact)
    move_stage.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Integration (real Postgres): end-to-end proof                                #
# --------------------------------------------------------------------------- #

from sqlalchemy import func, select  # noqa: E402

from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.models.automation import Automation  # noqa: E402
from app.models.automation_event import (  # noqa: E402
    EVENT_STATUS_PENDING,
    AutomationEvent,
)
from app.models.contact import Contact  # noqa: E402
from app.models.opportunity import Opportunity, OpportunityActivity  # noqa: E402
from app.models.pipeline import Pipeline, PipelineStage  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.schemas.opportunity import OpportunityCreate  # noqa: E402
from app.services.opportunities.opportunity_service import OpportunityService  # noqa: E402


@pytest.fixture
async def _fresh_engine_pool():
    """Dispose the shared asyncpg pool around each integration test.

    pytest-asyncio gives each test a fresh event loop; without disposing, the
    engine's pool can hold connections bound to a closed loop and surface as
    ``Event loop is closed`` when integration tests run back-to-back.
    """
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Move", slug=f"move-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _contact_row(db, workspace_id: uuid.UUID) -> Contact:
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Grace",
        last_name="Hopper",
        email=f"grace-{uuid.uuid4().hex[:6]}@example.com",
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _pipeline_with_stages(
    db, workspace_id: uuid.UUID
) -> tuple[Pipeline, PipelineStage, PipelineStage]:
    pipeline = Pipeline(workspace_id=workspace_id, name="Sales", is_active=True)
    db.add(pipeline)
    await db.flush()
    lead = PipelineStage(pipeline_id=pipeline.id, name="Lead", order=0, probability=10)
    scheduled = PipelineStage(
        pipeline_id=pipeline.id, name="Estimate Scheduled", order=1, probability=40
    )
    db.add_all([lead, scheduled])
    await db.flush()
    return pipeline, lead, scheduled


async def _opportunity(
    db,
    workspace_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    stage_id: uuid.UUID,
    contact_id: int | None,
) -> Opportunity:
    opp = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline_id,
        stage_id=stage_id,
        name="Backyard lighting",
        primary_contact_id=contact_id,
        probability=10,
        status="open",
        is_active=True,
    )
    db.add(opp)
    await db.flush()
    return opp


def _automation_ns(workspace_id: uuid.UUID) -> SimpleNamespace:
    """A minimal stand-in the action only reads .id / .workspace_id / .name from."""
    return SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace_id, name="move-auto")


async def _pending_stage_events(db, workspace_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(AutomationEvent)
        .where(
            AutomationEvent.workspace_id == workspace_id,
            AutomationEvent.event_type == "deal_stage_changed",
            AutomationEvent.status == EVENT_STATUS_PENDING,
        )
    )
    return int(result.scalar_one())


async def _stage_changed_activities(db, opportunity_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(OpportunityActivity)
        .where(
            OpportunityActivity.opportunity_id == opportunity_id,
            OpportunityActivity.activity_type == "stage_changed",
        )
    )
    return int(result.scalar_one())


@pytest.mark.integration
async def test_opportunity_created_event_moves_deal_end_to_end(_fresh_engine_pool) -> None:
    """The plan's flagship path: an opportunity_created automation whose action is
    move_to_stage advances the new deal via the event drain (payload carries the
    opportunity_id)."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact_row(db, ws.id)
        pipeline, lead, scheduled = await _pipeline_with_stages(db, ws.id)

        db.add(
            Automation(
                workspace_id=ws.id,
                name="On new deal -> Estimate Scheduled",
                trigger_type="opportunity_created",
                trigger_config={},
                actions=[
                    {
                        "type": "move_to_stage",
                        "config": {"stage_id": str(scheduled.id), "pipeline_id": str(pipeline.id)},
                    }
                ],
                is_active=True,
            )
        )
        await db.commit()

        created = await OpportunityService(db).create_opportunity(
            ws.id,
            OpportunityCreate(
                pipeline_id=pipeline.id,
                stage_id=lead.id,
                name="New deal",
                primary_contact_id=contact.id,
            ),
        )
        await db.commit()

        # Drain the queued opportunity_created event -> worker runs move_to_stage.
        worker = AutomationWorker()
        await worker._process_events(db)
        await db.commit()

        moved = await db.get(Opportunity, created.id)
        assert moved is not None
        assert moved.stage_id == scheduled.id
        assert moved.probability == 40


@pytest.mark.integration
async def test_move_to_stage_via_contact_resolution(_fresh_engine_pool) -> None:
    """With no opportunity_id in the payload, the action resolves the contact's
    newest open deal and moves it."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact_row(db, ws.id)
        pipeline, lead, scheduled = await _pipeline_with_stages(db, ws.id)
        opp = await _opportunity(db, ws.id, pipeline.id, lead.id, contact.id)
        await db.commit()

        worker = AutomationWorker()
        await worker._action_move_to_stage(
            _automation_ns(ws.id),
            contact,
            {"stage_id": str(scheduled.id)},
            {},  # no opportunity_id -> contact resolution
            db,
        )
        await db.commit()

        await db.refresh(opp)
        assert opp.stage_id == scheduled.id
        assert opp.probability == 40


@pytest.mark.integration
async def test_lead_created_automation_creates_contact_pipeline_opportunity(
    _fresh_engine_pool,
) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact_row(db, ws.id)
        pipeline, lead, _scheduled = await _pipeline_with_stages(db, ws.id)

        db.add(
            Automation(
                workspace_id=ws.id,
                name="On new lead -> New Lead pipeline",
                trigger_type="lead_created",
                trigger_config={},
                actions=[
                    {
                        "type": "move_to_stage",
                        "config": {"stage_id": str(lead.id), "pipeline_id": str(pipeline.id)},
                    }
                ],
                is_active=True,
            )
        )
        event = AutomationEvent(
            workspace_id=ws.id,
            event_type="lead_created",
            contact_id=contact.id,
            payload={"source": "lead_form"},
            status=EVENT_STATUS_PENDING,
        )
        db.add(event)
        await db.commit()

        await AutomationWorker()._process_events(db)
        await db.commit()

        created = (
            await db.execute(
                select(Opportunity).where(
                    Opportunity.workspace_id == ws.id,
                    Opportunity.primary_contact_id == contact.id,
                )
            )
        ).scalar_one()
        assert created.pipeline_id == pipeline.id
        assert created.stage_id == lead.id
        assert created.status == "open"
        assert created.probability == lead.probability
        await db.refresh(event)
        assert event.status == "processed"


@pytest.mark.integration
async def test_move_to_stage_records_activity_without_derived_event(_fresh_engine_pool) -> None:
    """Automation moves retain history but never emit a chainable stage event."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact_row(db, ws.id)
        pipeline, lead, scheduled = await _pipeline_with_stages(db, ws.id)
        opp = await _opportunity(db, ws.id, pipeline.id, lead.id, contact.id)

        # An active listener proves suppression even when an event would be consumed.
        db.add(
            Automation(
                workspace_id=ws.id,
                name="downstream",
                trigger_type="deal_stage_changed",
                trigger_config={},
                actions=[{"type": "apply_tag", "config": {"tag": "moved"}}],
                is_active=True,
            )
        )
        await db.commit()

        worker = AutomationWorker()
        automation = _automation_ns(ws.id)
        config = {"stage_id": str(scheduled.id)}
        payload = {"opportunity_id": str(opp.id)}

        # First move: real advance -> one activity, but no derived automation event.
        await worker._action_move_to_stage(automation, contact, config, payload, db)
        await db.commit()
        assert await _pending_stage_events(db, ws.id) == 0
        assert await _stage_changed_activities(db, opp.id) == 1
        await db.refresh(opp)
        assert opp.stage_id == scheduled.id

        # Second move to the same stage remains an idempotent no-op.
        await worker._action_move_to_stage(automation, contact, config, payload, db)
        await db.commit()
        assert await _pending_stage_events(db, ws.id) == 0
        assert await _stage_changed_activities(db, opp.id) == 1


@pytest.mark.integration
async def test_move_to_stage_invalid_stage_skipped(_fresh_engine_pool) -> None:
    """A stage id that isn't in the workspace is skipped without raising and the
    deal is left untouched."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact_row(db, ws.id)
        pipeline, lead, _scheduled = await _pipeline_with_stages(db, ws.id)
        opp = await _opportunity(db, ws.id, pipeline.id, lead.id, contact.id)
        await db.commit()

        worker = AutomationWorker()
        await worker._action_move_to_stage(
            _automation_ns(ws.id),
            contact,
            {"stage_id": str(uuid.uuid4())},  # random stage, not in this workspace
            {"opportunity_id": str(opp.id)},
            db,
        )
        await db.commit()

        await db.refresh(opp)
        assert opp.stage_id == lead.id  # unchanged
        assert await _stage_changed_activities(db, opp.id) == 0
