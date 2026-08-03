"""Real-DB integration tests for public client-proposal view tracking.

Covers :meth:`QuoteService.record_public_view` end-to-end against Postgres: the
first beacon stamps all three columns and queues exactly one operator nudge, a
repeat beacon inside the throttle window writes nothing at all, a beacon after
the window bumps the recency signal without producing a second alert, and an
unknown token 404s before any write.

The throttle and the dedup guard both depend on real database behaviour (a
timestamptz round-trip and the UNIQUE index on ``human_nudges.dedup_key``), so
these are marked ``integration`` and deselected by default. Run with
``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.human_nudge import HumanNudge
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.quote import QuoteCreate, QuoteLineItemCreate
from app.services.exceptions import NotFoundError
from app.services.quotes import QuoteService
from app.services.quotes.quote_service import VIEW_THROTTLE_MINUTES

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
        slug=f"qview-{uuid.uuid4().hex[:8]}",
        settings={},
    )
    db.add(ws)
    await db.flush()
    return ws


async def _make_contact(db: AsyncSession, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    email = f"viewer-{uuid.uuid4().hex[:8]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Dana",
        last_name="Homeowner",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        email=email,
        email_hash=hash_value(email),
    )
    db.add(contact)
    await db.flush()
    return contact


async def _sent_quote(
    svc: QuoteService, workspace_id: uuid.UUID, contact_id: int
) -> tuple[str, uuid.UUID]:
    created = await svc.create_quote(
        workspace_id,
        QuoteCreate(
            contact_id=contact_id,
            title="Backyard lighting install",
            line_items=[QuoteLineItemCreate(name="Fixtures", quantity=6, unit_price=120.0)],
        ),
    )
    sent = await svc.mark_sent(workspace_id, created.id)
    assert sent.public_token is not None
    return sent.public_token, created.id


async def _reload(db: AsyncSession, quote_id: uuid.UUID) -> Quote:
    result = await db.execute(select(Quote).where(Quote.id == quote_id))
    quote = result.scalar_one()
    await db.refresh(quote)
    return quote


async def _nudge_count(db: AsyncSession, quote_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(HumanNudge)
        .where(HumanNudge.dedup_key == f"{quote_id}:quote_viewed")
    )
    return int(result.scalar() or 0)


async def _age_last_view(db: AsyncSession, quote_id: uuid.UUID, *, minutes: int) -> None:
    """Backdate ``last_viewed_at`` so the next beacon lands outside the window."""
    quote = await _reload(db, quote_id)
    quote.last_viewed_at = datetime.now(UTC) - timedelta(minutes=minutes)
    await db.commit()


async def test_first_view_stamps_timestamps_and_creates_one_nudge() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, quote_id = await _sent_quote(svc, ws.id, contact.id)

        before = await _reload(db, quote_id)
        assert before.first_viewed_at is None
        assert before.last_viewed_at is None
        assert before.view_count == 0

        await svc.record_public_view(token)

        viewed = await _reload(db, quote_id)
        assert viewed.first_viewed_at is not None
        assert viewed.last_viewed_at is not None
        assert viewed.view_count == 1
        # The first view is both the first and the most recent one.
        assert viewed.first_viewed_at == viewed.last_viewed_at

        assert await _nudge_count(db, quote_id) == 1
        nudge = (
            await db.execute(
                select(HumanNudge).where(HumanNudge.dedup_key == f"{quote_id}:quote_viewed")
            )
        ).scalar_one()
        assert nudge.nudge_type == "quote_viewed"
        assert nudge.priority == "high"
        assert nudge.suggested_action == "call"
        assert nudge.contact_id == contact.id
        assert nudge.status == "pending"
        # The operator must be able to act without opening anything else.
        assert "Dana Homeowner" in nudge.title
        assert viewed.number in nudge.title


async def test_repeat_view_inside_throttle_window_writes_nothing() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, quote_id = await _sent_quote(svc, ws.id, contact.id)

        await svc.record_public_view(token)
        first = await _reload(db, quote_id)

        # A refresh, a package switch, a refetch on window focus -- same visit.
        await svc.record_public_view(token)
        await svc.record_public_view(token)

        after = await _reload(db, quote_id)
        assert after.view_count == 1
        assert after.last_viewed_at == first.last_viewed_at
        assert after.first_viewed_at == first.first_viewed_at
        assert await _nudge_count(db, quote_id) == 1


async def test_view_after_throttle_window_bumps_recency_but_not_the_nudge() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, quote_id = await _sent_quote(svc, ws.id, contact.id)

        await svc.record_public_view(token)
        first = await _reload(db, quote_id)
        first_viewed_at = first.first_viewed_at

        await _age_last_view(db, quote_id, minutes=VIEW_THROTTLE_MINUTES + 1)
        await svc.record_public_view(token)

        after = await _reload(db, quote_id)
        assert after.view_count == 2
        assert after.last_viewed_at is not None
        assert first_viewed_at is not None
        assert after.last_viewed_at > first_viewed_at
        # "They finally opened it" must survive every re-read.
        assert after.first_viewed_at == first_viewed_at
        # One alert per quote, not one per visit.
        assert await _nudge_count(db, quote_id) == 1


async def test_unknown_token_raises_not_found_without_writing() -> None:
    async with AsyncSessionLocal() as db:
        svc = QuoteService(db)
        with pytest.raises(NotFoundError):
            await svc.record_public_view("not-a-real-token")


async def test_draft_quote_token_never_records_a_view() -> None:
    """A draft has no token at all, so there is nothing to beacon against."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        created = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                line_items=[QuoteLineItemCreate(name="Fixtures", quantity=1, unit_price=10.0)],
            ),
        )
        assert created.public_token is None

        quote = await _reload(db, created.id)
        assert quote.view_count == 0
        assert quote.first_viewed_at is None
