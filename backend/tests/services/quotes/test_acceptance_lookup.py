"""Real-DB coverage for the quote lookup behind the acceptance intercept.

``find_outstanding_quote`` is the load-bearing half of the intercept and the
easiest part to get silently wrong: a mismatched status literal, a bad column,
or the wrong ordering all return ``None`` forever. The intercept then falls
through to the ordinary booking reply, which is exactly the bug it exists to
prevent — with no error, no log, and nothing to notice.

The unit suite mocks this function, so these tests run it against Postgres with
quotes built through the real ``QuoteService``. Marked ``integration`` and
deselected by default; run with ``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.schemas.quote import QuoteCreate, QuoteLineItemCreate
from app.services.quotes import QuoteService
from app.services.quotes.acceptance_detector import find_outstanding_quote

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Maxteriors Lighting",
        slug=f"acc-{uuid.uuid4().hex[:8]}",
        settings={},
    )
    db.add(ws)
    await db.flush()
    return ws


async def _make_contact(db: AsyncSession, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    email = f"greg-{uuid.uuid4().hex[:8]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Greg",
        last_name="Homeowner",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        email=email,
        email_hash=hash_value(email),
    )
    db.add(contact)
    await db.flush()
    return contact


async def _quote(svc: QuoteService, workspace_id: uuid.UUID, contact_id: int, title: str):
    return await svc.create_quote(
        workspace_id,
        QuoteCreate(
            contact_id=contact_id,
            title=title,
            line_items=[QuoteLineItemCreate(name="Fixtures", quantity=6, unit_price=120.0)],
        ),
    )


async def test_finds_the_quote_the_customer_is_replying_to() -> None:
    """The happy path the whole intercept depends on."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        created = await _quote(svc, ws.id, contact.id, "Roofline lighting")
        await svc.mark_sent(ws.id, created.id)

        found = await find_outstanding_quote(db, workspace_id=ws.id, contact_id=contact.id)

        assert found is not None, "a sent quote must be found, or the intercept never fires"
        assert found.id == created.id
        assert found.status == "sent"


async def test_a_draft_is_not_outstanding() -> None:
    """The customer has never seen a draft, so a 'yes' cannot be about one."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        created = await _quote(QuoteService(db), ws.id, contact.id, "Unsent draft")

        assert created.status == "draft"
        assert await find_outstanding_quote(db, workspace_id=ws.id, contact_id=contact.id) is None


async def test_an_already_approved_quote_stops_re_paging_the_team() -> None:
    """Without this, every later text from the customer re-triggers the handoff."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        created = await _quote(svc, ws.id, contact.id, "Already sold")
        await svc.mark_sent(ws.id, created.id)
        await svc.approve_quote(ws.id, created.id)

        assert await find_outstanding_quote(db, workspace_id=ws.id, contact_id=contact.id) is None


async def test_the_most_recent_sent_quote_wins() -> None:
    """A revised proposal is the one being accepted, not the superseded one."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        first = await _quote(svc, ws.id, contact.id, "Original")
        await svc.mark_sent(ws.id, first.id)
        second = await _quote(svc, ws.id, contact.id, "Revised after walkthrough")
        await svc.mark_sent(ws.id, second.id)

        found = await find_outstanding_quote(db, workspace_id=ws.id, contact_id=contact.id)

        assert found is not None
        assert found.id == second.id


async def test_another_workspace_quote_is_never_returned() -> None:
    """Multi-tenant safety: the lookup runs on inbound text before any auth check."""
    async with AsyncSessionLocal() as db:
        theirs = await _make_workspace(db)
        their_contact = await _make_contact(db, theirs.id)
        svc = QuoteService(db)
        their_quote = await _quote(svc, theirs.id, their_contact.id, "Their job")
        await svc.mark_sent(theirs.id, their_quote.id)

        mine = await _make_workspace(db)

        assert (
            await find_outstanding_quote(db, workspace_id=mine.id, contact_id=their_contact.id)
            is None
        )


async def test_no_contact_on_the_conversation_is_handled() -> None:
    """Inbound texts from unknown numbers have no contact_id."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        assert await find_outstanding_quote(db, workspace_id=ws.id, contact_id=None) is None
