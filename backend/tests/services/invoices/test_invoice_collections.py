"""Collections view: outstanding balance, lateness, and the unpaid filter.

``Invoice.status`` is only re-derived when an invoice is *mutated*, so an invoice
left alone past its due date keeps reading ``sent`` forever. Every figure in this
view is therefore computed from amounts and dates at read time. These tests pin
that: they deliberately construct invoices whose stored ``status`` is stale and
assert the response still reports the truth.

Pure functions (no DB) for the derivations; a real-DB test for the filter and the
book-wide total, because both are SQL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.invoice import Invoice, InvoiceLineItem
from app.models.workspace import Workspace
from app.services.invoices.invoice_service import (
    InvoiceService,
    invoice_balance_due,
    invoice_days_overdue,
)


def _invoice(
    *,
    total: float = 100.0,
    amount_paid: float = 0.0,
    status: str = "sent",
    due_date: date | None = None,
    sent_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        total=total,
        amount_paid=amount_paid,
        status=status,
        due_date=due_date,
        sent_at=sent_at,
    )


# --------------------------------------------------------------------------- #
# balance_due
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("total", "paid", "expected"),
    [
        (100.0, 0.0, 100.0),
        (100.0, 40.0, 60.0),
        (100.0, 100.0, 0.0),
        (100.0, 150.0, 0.0),  # overpaid never goes negative
        (0.0, 0.0, 0.0),
    ],
)
def test_balance_due(total: float, paid: float, expected: float) -> None:
    assert invoice_balance_due(_invoice(total=total, amount_paid=paid)) == expected


def test_void_invoice_owes_nothing() -> None:
    """Voiding is how a bill is cancelled, so it must not inflate what we're owed."""
    voided = _invoice(total=500.0, amount_paid=0.0, status="void")

    assert invoice_balance_due(voided) == 0.0
    assert invoice_days_overdue(voided) is None


# --------------------------------------------------------------------------- #
# days_overdue
# --------------------------------------------------------------------------- #
def test_days_overdue_counts_from_the_due_date() -> None:
    today = date(2026, 3, 20)
    invoice = _invoice(due_date=date(2026, 3, 10), sent_at=datetime.now(UTC))

    assert invoice_days_overdue(invoice, today=today) == 10


def test_stale_sent_status_still_reports_overdue() -> None:
    """The whole reason this is computed: the stored status says ``sent``."""
    invoice = _invoice(status="sent", due_date=date(2026, 1, 1), sent_at=datetime.now(UTC))

    assert invoice_days_overdue(invoice, today=date(2026, 1, 31)) == 30


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"due_date": None}, "no due date"),
        ({"sent_at": None}, "never sent to the customer"),
        ({"amount_paid": 100.0}, "already settled"),
        ({"due_date": date(2099, 1, 1)}, "not due yet"),
    ],
)
def test_not_overdue_cases(kwargs: dict, reason: str) -> None:
    base = {"due_date": date(2026, 1, 1), "sent_at": datetime.now(UTC)}
    invoice = _invoice(**{**base, **kwargs})

    assert invoice_days_overdue(invoice, today=date(2026, 6, 1)) is None, reason


def test_due_today_is_not_yet_late() -> None:
    today = date(2026, 5, 5)
    invoice = _invoice(due_date=today, sent_at=datetime.now(UTC))

    assert invoice_days_overdue(invoice, today=today) is None


# --------------------------------------------------------------------------- #
# unpaid filter + book-wide total (real DB)
# --------------------------------------------------------------------------- #
integration = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _seed(db, workspace_id: uuid.UUID, contact_id: int, **kwargs) -> Invoice:
    invoice = Invoice(
        workspace_id=workspace_id,
        contact_id=contact_id,
        number=f"INV-{uuid.uuid4().hex[:8]}",
        currency="USD",
        subtotal=kwargs.get("total", 100.0),
        tax_amount=0,
        discount_amount=0,
        **kwargs,
    )
    db.add(invoice)
    await db.flush()
    db.add(
        InvoiceLineItem(
            invoice_id=invoice.id,
            name="Work",
            quantity=1,
            unit_price=kwargs.get("total", 100.0),
            discount=0,
            total=kwargs.get("total", 100.0),
        )
    )
    await db.flush()
    return invoice


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unpaid_filter_and_outstanding_total() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Books", slug=f"books-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        contact = Contact(
            workspace_id=ws.id,
            first_name="Ida",
            last_name="Ledger",
            email=f"ida-{uuid.uuid4().hex[:6]}@example.com",
            phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
        )
        db.add(contact)
        await db.flush()

        sent_at = datetime.now(UTC) - timedelta(days=40)
        # Owed: 100 unpaid + 60 remaining on the partially paid one = 160.
        await _seed(db, ws.id, contact.id, total=100.0, amount_paid=0.0, status="sent",
                    sent_at=sent_at, due_date=date.today() - timedelta(days=30))
        await _seed(db, ws.id, contact.id, total=100.0, amount_paid=40.0, status="partial",
                    sent_at=sent_at)
        # Excluded: settled, and a void invoice that still carries a total.
        await _seed(db, ws.id, contact.id, total=250.0, amount_paid=250.0, status="paid")
        await _seed(db, ws.id, contact.id, total=999.0, amount_paid=0.0, status="void")
        await db.flush()

        page = await InvoiceService(db).list_invoices(ws.id, unpaid_only=True)

        assert page.total == 2, "only invoices that still owe money"
        assert page.outstanding_total == 160.0
        assert {round(item.balance_due, 2) for item in page.items} == {100.0, 60.0}

        overdue = next(item for item in page.items if item.balance_due == 100.0)
        assert overdue.days_overdue == 30

        # Unfiltered, the same book-wide figure is reported.
        everything = await InvoiceService(db).list_invoices(ws.id)
        assert everything.total == 4
        assert everything.outstanding_total == 160.0
