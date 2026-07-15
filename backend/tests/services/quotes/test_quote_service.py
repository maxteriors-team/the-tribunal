"""Real-DB integration tests for :class:`QuoteService`.

These hit Postgres (the per-workspace number sequence, the named ``quote_status``
enum, lazy expiry via a scoped UPDATE, and conversion into real ``Job`` /
``Invoice`` rows behave differently under a real engine than under mocks), so
they are marked ``integration`` and deselected by default. Run with
``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import Job, ServiceLocation
from app.models.invoice import Invoice
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.quote import (
    QuoteCreate,
    QuoteLineItemCreate,
    QuoteLineItemUpdate,
    QuoteUpdate,
)
from app.services.exceptions import ConflictError
from app.services.quotes import QuoteService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Quotes Co", slug=f"quo-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _make_contact(
    db: AsyncSession, workspace_id: uuid.UUID, *, email: str | None = None
) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Pat",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        email=email,
        email_hash=hash_value(email) if email else None,
    )
    db.add(contact)
    await db.flush()
    return contact


async def _make_location(
    db: AsyncSession, workspace_id: uuid.UUID, contact_id: int
) -> ServiceLocation:
    loc = ServiceLocation(workspace_id=workspace_id, contact_id=contact_id, name="Main House")
    db.add(loc)
    await db.flush()
    return loc


async def test_create_computes_totals_and_allocates_number() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)

        created = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                title="Backyard lighting",
                tax_amount=10.0,
                discount_amount=5.0,
                line_items=[
                    QuoteLineItemCreate(name="Labor", quantity=2, unit_price=100.0),
                    QuoteLineItemCreate(name="Parts", quantity=1, unit_price=50.0, discount=5.0),
                ],
            ),
            created_by_id=None,
        )

        # subtotal = (2*100) + (1*50 - 5) = 245; total = 245 + 10 - 5 = 250
        assert created.subtotal == 245.0
        assert created.total == 250.0
        assert created.status == "draft"
        assert created.title == "Backyard lighting"
        assert created.number == "QUO-000001"
        assert len(created.line_items) == 2

        second = await svc.create_quote(ws.id, QuoteCreate(line_items=[]), created_by_id=None)
        assert second.number == "QUO-000002"


async def test_number_sequence_is_per_workspace() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _make_workspace(db)
        ws_b = await _make_workspace(db)
        svc = QuoteService(db)

        a1 = await svc.create_quote(ws_a.id, QuoteCreate(line_items=[]))
        b1 = await svc.create_quote(ws_b.id, QuoteCreate(line_items=[]))

        assert a1.number == "QUO-000001"
        assert b1.number == "QUO-000001"


async def test_line_item_edits_recompute_totals() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(line_items=[QuoteLineItemCreate(name="Base", unit_price=100.0)]),
        )
        assert quote.total == 100.0

        quote = await svc.add_line_item(
            ws.id, quote.id, QuoteLineItemCreate(name="Extra", quantity=3, unit_price=10.0)
        )
        assert quote.total == 130.0

        extra = next(li for li in quote.line_items if li.name == "Extra")
        quote = await svc.update_line_item(
            ws.id, quote.id, extra.id, QuoteLineItemUpdate(quantity=5)
        )
        assert next(li for li in quote.line_items if li.name == "Extra").total == 50.0
        assert quote.total == 150.0

        base = next(li for li in quote.line_items if li.name == "Base")
        quote = await svc.remove_line_item(ws.id, quote.id, base.id)
        assert len(quote.line_items) == 1
        assert quote.total == 50.0


async def test_send_sets_status_and_timestamp() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id, QuoteCreate(line_items=[QuoteLineItemCreate(name="Job", unit_price=300.0)])
        )

        sent = await svc.mark_sent(ws.id, quote.id)
        assert sent.status == "sent"
        assert sent.sent_at is not None


async def test_send_allocates_public_token_once() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id, QuoteCreate(line_items=[QuoteLineItemCreate(name="Job", unit_price=300.0)])
        )
        # Drafts have no token.
        assert quote.public_token is None

        sent = await svc.mark_sent(ws.id, quote.id)
        assert sent.public_token is not None
        first_token = sent.public_token

        # Re-sending is idempotent for the token: a link already in a customer's
        # inbox must keep working.
        resent = await svc.mark_sent(ws.id, quote.id)
        assert resent.public_token == first_token


async def test_approve_and_decline_guards() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        q1 = await svc.create_quote(ws.id, QuoteCreate(line_items=[]))
        approved = await svc.approve_quote(ws.id, q1.id)
        assert approved.status == "approved"
        assert approved.approved_at is not None

        # Re-approving is idempotent; declining an approved quote is rejected.
        assert (await svc.approve_quote(ws.id, q1.id)).status == "approved"
        with pytest.raises(ConflictError):
            await svc.decline_quote(ws.id, q1.id, reason="too late")

        q2 = await svc.create_quote(ws.id, QuoteCreate(line_items=[]))
        declined = await svc.decline_quote(ws.id, q2.id, reason="too expensive")
        assert declined.status == "declined"
        assert declined.decline_reason == "too expensive"
        with pytest.raises(ConflictError):
            await svc.approve_quote(ws.id, q2.id)


async def test_locked_quote_rejects_edits() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id, QuoteCreate(line_items=[QuoteLineItemCreate(name="X", unit_price=10.0)])
        )
        await svc.approve_quote(ws.id, quote.id)

        with pytest.raises(ConflictError):
            await svc.update_quote(ws.id, quote.id, QuoteUpdate(title="changed"))
        with pytest.raises(ConflictError):
            await svc.add_line_item(ws.id, quote.id, QuoteLineItemCreate(name="Y", unit_price=1.0))


async def test_expired_quote_surfaces_on_read() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                line_items=[QuoteLineItemCreate(name="Job", unit_price=100.0)],
                expiry_date=date.today() + timedelta(days=7),
            ),
        )
        await svc.mark_sent(ws.id, quote.id)

        # Push the expiry into the past; the next read must flip sent -> expired.
        row = await db.get(Quote, quote.id)
        assert row is not None
        row.expiry_date = date.today() - timedelta(days=1)
        await db.commit()

        fetched = await svc.get_quote(ws.id, quote.id)
        assert fetched.status == "expired"


async def test_convert_creates_job_and_invoice_idempotently() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        location = await _make_location(db, ws.id, contact.id)
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                service_location_id=location.id,
                title="Install lighting",
                tax_amount=20.0,
                line_items=[
                    QuoteLineItemCreate(name="Labor", quantity=2, unit_price=150.0),
                    QuoteLineItemCreate(name="Fixtures", quantity=4, unit_price=25.0),
                ],
            ),
        )
        await svc.approve_quote(ws.id, quote.id)

        result = await svc.convert_quote(ws.id, quote.id)
        assert result.job_id is not None
        assert result.invoice_id is not None
        assert result.quote.converted_job_id == result.job_id
        assert result.quote.converted_invoice_id == result.invoice_id

        # The job carries the quote's title, contact, and site.
        job = await db.get(Job, result.job_id)
        assert job is not None
        assert job.title == "Install lighting"
        assert job.contact_id == contact.id
        assert job.service_location_id == location.id

        # The invoice copied the quote's line items and totals.
        from sqlalchemy import select  # local import keeps the header lean

        from app.models.invoice import InvoiceLineItem

        invoice = await db.get(Invoice, result.invoice_id)
        assert invoice is not None
        # subtotal = (2*150) + (4*25) = 400; total = 400 + 20 tax = 420
        assert float(invoice.subtotal) == 400.0
        assert float(invoice.total) == 420.0
        line_count = len(
            (
                await db.execute(
                    select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id)
                )
            )
            .scalars()
            .all()
        )
        assert line_count == 2

        # Re-converting returns the same ids and creates no duplicates.
        again = await svc.convert_quote(ws.id, quote.id)
        assert again.job_id == result.job_id
        assert again.invoice_id == result.invoice_id


async def test_convert_schedules_job_when_window_supplied() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        location = await _make_location(db, ws.id, contact.id)
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                service_location_id=location.id,
                title="Install lighting",
                line_items=[QuoteLineItemCreate(name="Labor", unit_price=150.0)],
            ),
        )
        await svc.approve_quote(ws.id, quote.id)

        start = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
        end = start + timedelta(hours=3)
        result = await svc.convert_quote(
            ws.id,
            quote.id,
            create_invoice=False,
            scheduled_start=start,
            scheduled_end=end,
        )

        assert result.job_id is not None
        job = await db.get(Job, result.job_id)
        assert job is not None
        # The window is stored and the job lands on the calendar as scheduled.
        assert job.scheduled_start == start
        assert job.scheduled_end == end
        assert job.status == "scheduled"


async def test_convert_requires_approved_status() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                line_items=[QuoteLineItemCreate(name="Job", unit_price=100.0)],
            ),
        )
        await svc.mark_sent(ws.id, quote.id)

        with pytest.raises(ConflictError):
            await svc.convert_quote(ws.id, quote.id)
