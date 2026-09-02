"""Focused regressions for invoice-driven opportunity lifecycle transitions."""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.opportunity import Opportunity, OpportunityActivity, OpportunityTask
from app.models.workspace import Workspace
from app.schemas.deal_lifecycle import DealLifecycleSettings
from app.schemas.invoice import InvoiceManualPaymentCreate
from app.services.invoices.invoice_service import InvoiceService
from app.services.opportunities.invoice_lifecycle import transition_invoice_opportunity


class _Result:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


def _db() -> MagicMock:
    db = MagicMock()
    db.get = AsyncMock()
    db.scalar = AsyncMock()
    scalar_rows = MagicMock()
    scalar_rows.all.return_value = []
    db.scalars = AsyncMock(return_value=scalar_rows)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _configuration(pipeline_id: uuid.UUID) -> DealLifecycleSettings:
    return DealLifecycleSettings(
        pipeline_id=pipeline_id,
        new_lead_stage_id=uuid.uuid4(),
        contacted_no_answer_stage_id=uuid.uuid4(),
        visit_demo_scheduled_stage_id=uuid.uuid4(),
        qualified_stage_id=uuid.uuid4(),
        quote_follow_up_stage_id=uuid.uuid4(),
        won_stage_id=uuid.uuid4(),
        job_completed_stage_id=uuid.uuid4(),
        unqualified_stage_id=uuid.uuid4(),
        follow_up_assignee_user_id=42,
    )


def _workspace(workspace_id: uuid.UUID, config: DealLifecycleSettings) -> SimpleNamespace:
    return SimpleNamespace(
        id=workspace_id,
        settings={"deal_lifecycle": config.model_dump(mode="json")},
    )


def _stage(
    stage_id: uuid.UUID,
    name: str,
    *,
    order: int,
    stage_type: str = "active",
    probability: int = 50,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=stage_id,
        name=name,
        order=order,
        stage_type=stage_type,
        probability=probability,
    )


def _opportunity(
    workspace_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    stage_id: uuid.UUID,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        pipeline_id=pipeline_id,
        stage_id=stage_id,
        primary_contact_id=11,
        name="Patio lighting",
        status="open",
        is_active=True,
        probability=20,
        stage_changed_at=None,
        closed_date=None,
        closed_by_id=9,
        lost_reason="old value",
    )


def _invoice(
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID | None,
    *,
    total: float = 100.0,
    amount_paid: float = 0.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        opportunity_id=opportunity_id,
        contact_id=11,
        number="INV-1042",
        currency="USD",
        total=total,
        amount_paid=amount_paid,
        status="draft",
        sent_at=None,
        paid_at=None,
        due_date=date.today() + timedelta(days=7),
        public_token=None,
        payment_method=None,
        payment_recorded_by_id=None,
        manual_payment_amount=None,
        manual_payment_reference=None,
        manual_payment_idempotency_key=None,
        stripe_payment_intent_id=None,
        stripe_checkout_session_id=None,
    )


def _wire_db(
    db: MagicMock,
    workspace: SimpleNamespace,
    opportunity: SimpleNamespace,
    *,
    scalar_results: list[object],
    execute_results: list[object],
) -> None:
    async def get(model: object, _resource_id: object) -> object | None:
        if model is Workspace:
            return workspace
        if model is Opportunity:
            return opportunity
        return None

    db.get.side_effect = get
    db.scalar.side_effect = scalar_results
    db.execute.side_effect = [_Result(value) for value in execute_results]


async def test_unlinked_invoice_never_queries_or_moves_deal() -> None:
    db = _db()
    invoice = _invoice(uuid.uuid4(), None)

    assert await transition_invoice_opportunity(db, invoice, transition="sent") is False
    db.get.assert_not_awaited()
    db.scalar.assert_not_awaited()
    db.add.assert_not_called()


async def test_sent_invoice_moves_deal_forward_with_invoice_audit() -> None:
    workspace_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    config = _configuration(pipeline_id)
    current = _stage(uuid.uuid4(), "Visit/Demo Scheduled", order=3, probability=30)
    target = _stage(config.quote_follow_up_stage_id, "Quote Follow Up", order=5, probability=60)
    opportunity = _opportunity(workspace_id, pipeline_id, current.id)
    invoice = _invoice(workspace_id, opportunity.id)
    invoice.sent_at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    db = _db()
    _wire_db(
        db,
        _workspace(workspace_id, config),
        opportunity,
        scalar_results=[target, opportunity, current],
        execute_results=[target, current],
    )

    with patch(
        "app.services.opportunities.opportunity_service.emit_automation_event",
        new=AsyncMock(),
    ) as stage_event:
        changed = await transition_invoice_opportunity(db, invoice, transition="sent")

    assert changed is True
    assert opportunity.stage_id == target.id
    assert opportunity.probability == 60
    additions = [call.args[0] for call in db.add.call_args_list]
    tasks = [addition for addition in additions if isinstance(addition, OpportunityTask)]
    assert [task.due_at for task in tasks] == [
        datetime(2026, 9, 2, 12, tzinfo=UTC),
        datetime(2026, 9, 4, 12, tzinfo=UTC),
    ]
    assert all(task.assigned_user_id == 42 for task in tasks)
    activity = next(addition for addition in additions if isinstance(addition, OpportunityActivity))
    assert str(invoice.id) in activity.description
    assert "was sent" in activity.description
    assert stage_event.await_args.kwargs["payload"]["source"] == "invoice_sent"
    db.commit.assert_not_awaited()


async def test_paid_invoice_moves_deal_to_won_and_closes_status() -> None:
    workspace_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    config = _configuration(pipeline_id)
    current = _stage(uuid.uuid4(), "Quote Follow Up", order=5, probability=60)
    target = _stage(
        config.won_stage_id,
        "Won",
        order=6,
        stage_type="won",
        probability=100,
    )
    opportunity = _opportunity(workspace_id, pipeline_id, current.id)
    invoice = _invoice(workspace_id, opportunity.id, amount_paid=100)
    invoice.paid_at = datetime(2026, 9, 1, 15, tzinfo=UTC)
    db = _db()
    _wire_db(
        db,
        _workspace(workspace_id, config),
        opportunity,
        scalar_results=[target, opportunity],
        execute_results=[target, current],
    )

    with patch(
        "app.services.opportunities.opportunity_service.emit_automation_event",
        new=AsyncMock(),
    ) as stage_event:
        changed = await transition_invoice_opportunity(db, invoice, transition="paid")

    assert changed is True
    assert opportunity.stage_id == target.id
    assert opportunity.status == "won"
    assert opportunity.closed_date == date(2026, 9, 1)
    assert opportunity.closed_by_id is None
    assert opportunity.lost_reason is None
    activities = [call.args[0] for call in db.add.call_args_list]
    assert [activity.activity_type for activity in activities] == [
        "stage_changed",
        "status_changed",
    ]
    assert all(str(invoice.id) in activity.description for activity in activities)
    assert stage_event.await_args.kwargs["payload"]["source"] == "invoice_paid"


@pytest.mark.parametrize("terminal", ["status", "job_completed", "unqualified"])
async def test_invoice_transition_never_overwrites_terminal_deal(terminal: str) -> None:
    workspace_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    config = _configuration(pipeline_id)
    target = _stage(config.won_stage_id, "Won", order=6, stage_type="won")
    stage_id = uuid.uuid4()
    if terminal == "job_completed":
        stage_id = config.job_completed_stage_id
    elif terminal == "unqualified":
        stage_id = config.unqualified_stage_id
    opportunity = _opportunity(workspace_id, pipeline_id, stage_id)
    if terminal == "status":
        opportunity.status = "lost"
    invoice = _invoice(workspace_id, opportunity.id, amount_paid=100)
    invoice.paid_at = datetime.now(UTC)
    db = _db()
    _wire_db(
        db,
        _workspace(workspace_id, config),
        opportunity,
        scalar_results=[target, opportunity],
        execute_results=[],
    )

    assert await transition_invoice_opportunity(db, invoice, transition="paid") is False
    db.add.assert_not_called()


async def test_sent_invoice_never_reopens_won_stage() -> None:
    workspace_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    config = _configuration(pipeline_id)
    target = _stage(config.quote_follow_up_stage_id, "Quote Follow Up", order=5)
    opportunity = _opportunity(workspace_id, pipeline_id, config.won_stage_id)
    invoice = _invoice(workspace_id, opportunity.id)
    db = _db()
    _wire_db(
        db,
        _workspace(workspace_id, config),
        opportunity,
        scalar_results=[target, opportunity],
        execute_results=[],
    )

    assert await transition_invoice_opportunity(db, invoice, transition="sent") is False
    assert opportunity.stage_id == config.won_stage_id
    db.add.assert_not_called()


async def test_sent_invoice_does_not_drag_a_later_stage_backward() -> None:
    workspace_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    config = _configuration(pipeline_id)
    target = _stage(config.quote_follow_up_stage_id, "Quote Follow Up", order=5)
    later = _stage(uuid.uuid4(), "Installation Scheduled", order=6)
    opportunity = _opportunity(workspace_id, pipeline_id, later.id)
    invoice = _invoice(workspace_id, opportunity.id)
    db = _db()
    _wire_db(
        db,
        _workspace(workspace_id, config),
        opportunity,
        scalar_results=[target, opportunity, later],
        execute_results=[],
    )

    assert await transition_invoice_opportunity(db, invoice, transition="sent") is False
    assert opportunity.stage_id == later.id
    db.add.assert_not_called()


async def test_invoice_send_loader_locks_tenant_invoice() -> None:
    workspace_id = uuid.uuid4()
    invoice = _invoice(workspace_id, uuid.uuid4())
    db = _db()
    db.execute.return_value = _Result(invoice)

    loaded = await InvoiceService(db)._load_for_send(workspace_id, invoice.id)

    assert loaded is invoice
    statement = str(db.execute.await_args.args[0])
    assert "invoices.workspace_id" in statement
    assert "FOR UPDATE" in statement


async def test_invoice_events_include_deal_and_run_lifecycle_once() -> None:
    workspace_id = uuid.uuid4()
    opportunity_id = uuid.uuid4()
    db = _db()
    service = InvoiceService(db)
    sent_invoice = _invoice(workspace_id, opportunity_id)
    paid_invoice = _invoice(workspace_id, opportunity_id, amount_paid=100)

    with (
        patch(
            "app.services.invoices.invoice_service.emit_automation_event",
            new=AsyncMock(),
        ) as emit_event,
        patch(
            "app.services.invoices.invoice_service.transition_invoice_opportunity",
            new=AsyncMock(),
        ) as transition,
    ):
        await service._transition_to_sent(workspace_id, sent_invoice)
        await service._transition_to_sent(workspace_id, sent_invoice)
        assert await service._transition_to_fully_paid(
            paid_invoice,
            payment_amount=100,
            payment_event_id="pi_paid",
            queue_receipt=False,
        )
        assert not await service._transition_to_fully_paid(
            paid_invoice,
            payment_amount=100,
            payment_event_id="pi_paid",
            queue_receipt=False,
        )

    assert transition.await_args_list[0].kwargs["transition"] == "sent"
    assert transition.await_args_list[1].kwargs["transition"] == "paid"
    assert transition.await_count == 2
    assert [call.kwargs["payload"]["opportunity_id"] for call in emit_event.await_args_list] == [
        str(opportunity_id),
        str(opportunity_id),
    ]


async def test_partial_payment_does_not_move_deal_until_fully_paid() -> None:
    workspace_id = uuid.uuid4()
    invoice = _invoice(workspace_id, uuid.uuid4(), amount_paid=50)
    db = _db()
    service = InvoiceService(db)

    with (
        patch(
            "app.services.invoices.invoice_service.emit_automation_event",
            new=AsyncMock(),
        ) as emit_event,
        patch(
            "app.services.invoices.invoice_service.transition_invoice_opportunity",
            new=AsyncMock(),
        ) as transition,
    ):
        changed = await service._transition_to_fully_paid(
            invoice,
            payment_amount=50,
            payment_event_id="pi_partial",
            queue_receipt=False,
        )

    assert changed is False
    assert invoice.status == "partial"
    emit_event.assert_not_awaited()
    transition.assert_not_awaited()


async def test_manual_and_card_final_payments_share_paid_transition() -> None:
    workspace_id = uuid.uuid4()
    manual_invoice = _invoice(workspace_id, uuid.uuid4(), amount_paid=50)
    manual_payment = InvoiceManualPaymentCreate(
        payment_method="cash",
        amount=50,
        idempotency_key=uuid.uuid4(),
    )
    manual_db = _db()
    manual_service = InvoiceService(manual_db)
    manual_service._transition_to_fully_paid = AsyncMock(return_value=True)

    balance = await manual_service._apply_manual_payment(
        manual_invoice,
        manual_payment,
        amount=50,
        reference=None,
        recorded_by_id=7,
    )
    assert balance == 0
    manual_service._transition_to_fully_paid.assert_awaited_once()

    card_invoice = _invoice(workspace_id, uuid.uuid4(), amount_paid=50)
    card_db = _db()
    card_service = InvoiceService(card_db)
    card_service._load_locked_invoice = AsyncMock(return_value=card_invoice)
    card_service._transition_to_fully_paid = AsyncMock(return_value=True)
    card_service._notify_payment_received = AsyncMock()
    card_db.scalar.return_value = None

    assert await card_service.record_payment(
        card_invoice,
        50,
        payment_intent_id="pi_final",
    )
    card_service._transition_to_fully_paid.assert_awaited_once()
