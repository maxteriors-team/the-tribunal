"""End-to-end DB-backed tests for event-based automation triggers.

Marked ``integration`` (run with ``-m integration``); these hit the real
Postgres engine. Each test wires a real domain action (or a direct event emit)
through the ``automation_events`` queue and the ``AutomationWorker`` event
drain, then asserts the automation's action ran.

Verifying ``apply_tag`` is the cheapest fully-local proof that an automation
executed: it writes a ``ContactTag`` row with no external provider.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.models.automation import Automation
from app.models.automation_event import (
    EVENT_STATUS_PENDING,
    EVENT_STATUS_PROCESSED,
    AutomationEvent,
)
from app.models.automation_execution import AutomationExecution
from app.models.contact import Contact
from app.models.field_service import JobStatus
from app.models.invoice import Invoice
from app.models.pipeline import Pipeline, PipelineStage
from app.models.review_request import ReviewRequest, ReviewRequestChannel, ReviewRequestStatus
from app.models.tag import ContactTag, Tag
from app.models.workspace import Workspace
from app.schemas.invoice import InvoiceCreate, InvoiceLineItemCreate
from app.schemas.opportunity import OpportunityCreate, OpportunityUpdate
from app.schemas.quote import QuoteCreate, QuoteLineItemCreate
from app.services.automations.events import (
    EVENT_KNOWLEDGE_DOCUMENT_UPLOADED,
    EVENT_MISSED_CALL,
    EVENT_ROLEPLAY_COMPLETED,
    emit_automation_event,
)
from app.services.invoices import InvoiceService
from app.services.jobs import JobService
from app.services.opportunities.opportunity_service import OpportunityService
from app.services.quotes import QuoteService
from app.services.reviews.review_service import ReviewService
from app.workers.automation_worker import AutomationWorker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared asyncpg pool around each test.

    pytest-asyncio gives each test a fresh event loop; without disposing, the
    engine's pool can hold connections bound to a closed loop and surface as
    ``Event loop is closed`` when integration tests run back-to-back.
    """
    await engine.dispose()
    yield
    await engine.dispose()


# --------------------------------------------------------------------------- #
# Builders                                                                     #
# --------------------------------------------------------------------------- #


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Auto", slug=f"auto-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Grace",
        last_name="Hopper",
        email=f"grace-{uuid.uuid4().hex[:6]}@example.com",
        phone_number=phone,
    )
    db.add(contact)
    await db.flush()
    return contact


async def _automation(db, workspace_id: uuid.UUID, trigger_type: str, tag: str) -> Automation:
    automation = Automation(
        workspace_id=workspace_id,
        name=f"{trigger_type} -> tag",
        trigger_type=trigger_type,
        trigger_config={},
        actions=[{"type": "apply_tag", "config": {"tag": tag}}],
        is_active=True,
    )
    db.add(automation)
    await db.flush()
    return automation


async def _contact_has_tag(db, contact_id: int, tag: str) -> bool:
    result = await db.execute(
        select(ContactTag.id)
        .join(Tag, Tag.id == ContactTag.tag_id)
        .where(ContactTag.contact_id == contact_id, Tag.name == tag)
    )
    return result.first() is not None


async def _drain(db) -> None:
    """Run the worker's event-draining path against the open session."""
    worker = AutomationWorker()
    await worker._process_events(db)
    await db.flush()


# --------------------------------------------------------------------------- #
# Real-service emission paths                                                  #
# --------------------------------------------------------------------------- #


async def test_review_rating_emits_and_runs_automations() -> None:
    """ReviewService.submit_rating fires review_received + review_request_response."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _automation(db, ws.id, "review_received", "got-review")
        await _automation(db, ws.id, "review_request_response", "review-responded")

        review_request = ReviewRequest(
            workspace_id=ws.id,
            contact_id=contact.id,
            channel=ReviewRequestChannel.SMS,
            status=ReviewRequestStatus.SENT,
        )
        db.add(review_request)
        await db.commit()
        token = review_request.token

        # Real domain action: recipient submits a 5-star rating.
        await ReviewService(db).submit_rating(token, 5)

        # Two pending events should now exist.
        pending = await db.execute(
            select(AutomationEvent).where(
                AutomationEvent.workspace_id == ws.id,
                AutomationEvent.status == EVENT_STATUS_PENDING,
            )
        )
        assert len(pending.scalars().all()) == 2

        await _drain(db)
        await db.commit()

        assert await _contact_has_tag(db, contact.id, "got-review")
        assert await _contact_has_tag(db, contact.id, "review-responded")


async def test_opportunity_created_runs_automation() -> None:
    """OpportunityService.create_opportunity fires opportunity_created."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _automation(db, ws.id, "opportunity_created", "new-deal")

        pipeline = Pipeline(workspace_id=ws.id, name="Sales", is_active=True)
        db.add(pipeline)
        await db.flush()
        stage = PipelineStage(pipeline_id=pipeline.id, name="Lead", order=0, probability=10)
        db.add(stage)
        await db.commit()

        await OpportunityService(db).create_opportunity(
            ws.id,
            OpportunityCreate(
                pipeline_id=pipeline.id,
                stage_id=stage.id,
                name="Big deal",
                primary_contact_id=contact.id,
            ),
        )

        await _drain(db)
        await db.commit()

        assert await _contact_has_tag(db, contact.id, "new-deal")


async def test_deal_stage_changed_runs_automation() -> None:
    """OpportunityService.update_opportunity fires deal_stage_changed on move."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _automation(db, ws.id, "deal_stage_changed", "deal-moved")

        pipeline = Pipeline(workspace_id=ws.id, name="Sales", is_active=True)
        db.add(pipeline)
        await db.flush()
        stage_a = PipelineStage(pipeline_id=pipeline.id, name="Lead", order=0, probability=10)
        stage_b = PipelineStage(pipeline_id=pipeline.id, name="Won", order=1, probability=100)
        db.add_all([stage_a, stage_b])
        await db.commit()

        created = await OpportunityService(db).create_opportunity(
            ws.id,
            OpportunityCreate(
                pipeline_id=pipeline.id,
                stage_id=stage_a.id,
                name="Movable deal",
                primary_contact_id=contact.id,
            ),
        )
        # Drain the opportunity_created event first (no listener -> none queued).
        await OpportunityService(db).update_opportunity(
            ws.id,
            created.id,
            OpportunityUpdate(stage_id=stage_b.id),
            user_id=1,
        )

        await _drain(db)
        await db.commit()

        assert await _contact_has_tag(db, contact.id, "deal-moved")


async def test_quote_lifecycle_emits_and_runs_automations() -> None:
    """QuoteService send/approve/convert each fire their lifecycle trigger."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _automation(db, ws.id, "quote_sent", "quote-sent")
        await _automation(db, ws.id, "quote_approved", "quote-approved")
        await _automation(db, ws.id, "quote_converted", "quote-converted")
        await db.commit()

        quote = await QuoteService(db).create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                title="Roof repair",
                line_items=[QuoteLineItemCreate(name="Labor", quantity=1, unit_price=500)],
            ),
        )

        await QuoteService(db).mark_sent(ws.id, quote.id)
        await _drain(db)
        await db.commit()
        assert await _contact_has_tag(db, contact.id, "quote-sent")

        await QuoteService(db).approve_quote(ws.id, quote.id)
        await _drain(db)
        await db.commit()
        assert await _contact_has_tag(db, contact.id, "quote-approved")

        await QuoteService(db).convert_quote(ws.id, quote.id)
        await _drain(db)
        await db.commit()
        assert await _contact_has_tag(db, contact.id, "quote-converted")

        # Re-converting an already-converted quote is a no-op and must not
        # enqueue a second event (idempotent — no double-fire).
        await QuoteService(db).convert_quote(ws.id, quote.id)
        pending = await db.execute(
            select(AutomationEvent).where(
                AutomationEvent.workspace_id == ws.id,
                AutomationEvent.status == EVENT_STATUS_PENDING,
            )
        )
        assert pending.scalars().all() == []


async def test_invoice_sent_and_paid_emit_on_transition() -> None:
    """InvoiceService fires invoice_sent on first send and invoice_paid only on
    the transition into fully paid (not on a partial payment)."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _automation(db, ws.id, "invoice_sent", "invoice-sent")
        await _automation(db, ws.id, "invoice_paid", "invoice-paid")
        await db.commit()

        created = await InvoiceService(db).create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Labor", quantity=1, unit_price=200)],
            ),
        )

        await InvoiceService(db).mark_sent(ws.id, created.id)
        await _drain(db)
        await db.commit()
        assert await _contact_has_tag(db, contact.id, "invoice-sent")

        invoice = await db.get(Invoice, created.id)
        assert invoice is not None

        # A partial payment leaves the invoice ``partial`` -> no invoice_paid.
        await InvoiceService(db).record_payment(invoice, 50.0, payment_intent_id="pi_partial")
        await _drain(db)
        await db.commit()
        assert not await _contact_has_tag(db, contact.id, "invoice-paid")

        # Settling the balance flips it to ``paid`` and emits exactly once.
        await InvoiceService(db).record_payment(invoice, 150.0, payment_intent_id="pi_full")
        await _drain(db)
        await db.commit()
        assert await _contact_has_tag(db, contact.id, "invoice-paid")


async def test_job_scheduled_and_completed_emit() -> None:
    """JobService fires job_scheduled when a job enters a window and job_completed
    when its status advances to completed."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _automation(db, ws.id, "job_scheduled", "job-scheduled")
        await _automation(db, ws.id, "job_completed", "job-completed")
        await db.commit()

        start = datetime(2026, 6, 1, 9, tzinfo=UTC)
        end = datetime(2026, 6, 1, 11, tzinfo=UTC)
        job = await JobService(db).create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "Maintenance visit",
                "scheduled_start": start,
                "scheduled_end": end,
                "technician_ids": [],
            },
        )
        await db.commit()
        await _drain(db)
        await db.commit()
        assert await _contact_has_tag(db, contact.id, "job-scheduled")

        await JobService(db).update(job.id, ws.id, {"status": JobStatus.COMPLETED})
        await db.commit()
        await _drain(db)
        await db.commit()
        assert await _contact_has_tag(db, contact.id, "job-completed")


# --------------------------------------------------------------------------- #
# Direct-emit worker paths (services with heavy external deps)                 #
# --------------------------------------------------------------------------- #


async def test_missed_call_event_runs_automation() -> None:
    """A queued missed_call event drives its automation's action."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _automation(db, ws.id, "missed_call", "missed-us")

        await emit_automation_event(
            db,
            workspace_id=ws.id,
            event_type=EVENT_MISSED_CALL,
            contact_id=contact.id,
            payload={"call_outcome": "no_answer"},
        )
        await db.commit()

        await _drain(db)
        await db.commit()

        assert await _contact_has_tag(db, contact.id, "missed-us")


@pytest.mark.parametrize(
    "event_type",
    [EVENT_ROLEPLAY_COMPLETED, EVENT_KNOWLEDGE_DOCUMENT_UPLOADED],
)
async def test_contactless_event_completes(event_type: str) -> None:
    """Contactless events (roleplay/knowledge) still record a completed run."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        automation = await _automation(db, ws.id, event_type, "n/a")

        event = await emit_automation_event(
            db,
            workspace_id=ws.id,
            event_type=event_type,
            contact_id=None,
            payload={"run_id": "x"},
        )
        assert event is not None
        await db.commit()

        await _drain(db)
        await db.commit()

        # Event processed and a contactless execution recorded as completed.
        await db.refresh(event)
        assert event.status == EVENT_STATUS_PROCESSED
        result = await db.execute(
            select(AutomationExecution).where(
                AutomationExecution.automation_id == automation.id,
                AutomationExecution.event_id == event.id,
            )
        )
        execution = result.scalar_one()
        assert execution.status == "completed"
        assert execution.contact_id is None


# --------------------------------------------------------------------------- #
# Emit gating + dedupe                                                         #
# --------------------------------------------------------------------------- #


async def test_emit_skips_without_active_automation() -> None:
    """No event is queued when no active automation listens for the trigger."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)

        event = await emit_automation_event(
            db,
            workspace_id=ws.id,
            event_type=EVENT_MISSED_CALL,
            contact_id=contact.id,
        )
        assert event is None


async def test_event_dedupe_on_redrain() -> None:
    """Re-draining a processed event never double-runs an automation."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        automation = await _automation(db, ws.id, "missed_call", "dedupe-tag")

        event = await emit_automation_event(
            db,
            workspace_id=ws.id,
            event_type=EVENT_MISSED_CALL,
            contact_id=contact.id,
        )
        assert event is not None
        await db.commit()

        await _drain(db)
        await db.commit()

        # Force the same event back to pending and drain again.
        event.status = EVENT_STATUS_PENDING
        event.processed_at = None
        await db.commit()
        await _drain(db)
        await db.commit()

        result = await db.execute(
            select(AutomationExecution).where(
                AutomationExecution.automation_id == automation.id,
                AutomationExecution.event_id == event.id,
            )
        )
        assert len(result.scalars().all()) == 1
