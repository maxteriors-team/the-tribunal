"""What a renewal draft is worth, once it has actually been saved.

``tests/services/seasonal/test_christmas_renewal_quote`` covers the pure copy
rules. This covers the step after: the builder is pure and only copies line
items, so *something* has to derive the quote-level fields from them. Nothing
did, and the two consequences were both customer-visible:

* the draft totalled **$0** with $2,400 of line items on it, so a rep who sent
  it without opening it quoted the whole job for free;
* ``primary_service`` stayed null, and that is the field next season's renewal
  reads to decide a quote was holiday-lighting work — so this year's renewal
  could not itself be renewed.

Marked ``integration``: this is the persisted round trip, which is exactly where
the bug lived.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.quote import Quote, QuoteLineItem
from app.models.recurring_job import (
    RecurrenceFrequency,
    RecurringJobTemplate,
    ServicePlanType,
)
from app.models.workspace import Workspace
from app.services.quotes import QuoteService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

LAST_SEASON = datetime(2025, 11, 20, 12, 0, tzinfo=UTC)
ROOFLINE, TREES = 1620.0, 780.0


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


async def _sold_last_season(db: AsyncSession) -> tuple[Workspace, Contact]:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Renewals",
        slug=f"renew-{uuid.uuid4().hex[:8]}",
        settings={"pricing": {"christmas": {"enabled": True}}},
    )
    db.add(ws)
    await db.flush()

    email = f"grace-{uuid.uuid4().hex[:6]}@example.com"
    contact = Contact(
        workspace_id=ws.id,
        first_name="Grace",
        last_name="Hopper",
        email=email,
        email_hash=hash_value(email),
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()

    quote = Quote(
        workspace_id=ws.id,
        contact_id=contact.id,
        number=f"QUO-{uuid.uuid4().int % 1_000_000:06d}",
        status="approved",
        primary_service="christmas_lights",
        currency="USD",
        subtotal=ROOFLINE + TREES,
        tax_amount=0,
        discount_amount=0,
        total=ROOFLINE + TREES,
        created_at=LAST_SEASON,
        approved_at=LAST_SEASON,
    )
    db.add(quote)
    await db.flush()
    for name, price in (("C9 Roofline — 180 ft", ROOFLINE), ("Wrapped trees (3)", TREES)):
        db.add(
            QuoteLineItem(
                quote_id=quote.id,
                name=name,
                quantity=1,
                unit_price=price,
                discount=0,
                total=price,
                service_category="christmas",
            )
        )
    for title in ("Christmas Install", "Christmas Takedown"):
        db.add(
            RecurringJobTemplate(
                workspace_id=ws.id,
                contact_id=contact.id,
                plan_type=str(ServicePlanType.CHRISTMAS_LIGHTS),
                source_quote_id=quote.id,
                title=title,
                frequency=str(RecurrenceFrequency.YEARLY),
                interval=1,
                created_at=LAST_SEASON,
                next_run_at=LAST_SEASON + timedelta(days=365),
            )
        )
    await db.flush()
    return ws, contact


async def test_a_renewal_is_worth_what_its_line_items_are_worth():
    """The draft shipped at $0 with $2,400 of work on it. Never again."""
    async with AsyncSessionLocal() as db:
        ws, contact = await _sold_last_season(db)

        renewal = await QuoteService(db).renew_last_season(ws.id, contact.id)

        assert renewal.subtotal == ROOFLINE + TREES
        assert renewal.total == ROOFLINE + TREES
        assert {li.total for li in renewal.line_items} == {ROOFLINE, TREES}
        await db.rollback()


async def test_a_renewal_can_itself_be_renewed_next_season():
    """`primary_service` is how next season recognises this as holiday work.

    Left null, the renewal is invisible to the very feature that created it.
    """
    async with AsyncSessionLocal() as db:
        ws, contact = await _sold_last_season(db)

        renewal = await QuoteService(db).renew_last_season(ws.id, contact.id)

        assert renewal.primary_service == "christmas"
        await db.rollback()


async def test_a_renewal_starts_as_an_unsent_draft():
    """It is a new offer, not a record of the settled sale it came from."""
    async with AsyncSessionLocal() as db:
        ws, contact = await _sold_last_season(db)

        renewal = await QuoteService(db).renew_last_season(ws.id, contact.id)

        assert renewal.status == "draft"
        assert renewal.sent_at is None
        assert renewal.approved_at is None
        assert renewal.public_token is None
        await db.rollback()


async def test_renewing_a_customer_from_another_workspace_is_not_possible():
    async with AsyncSessionLocal() as db:
        mine, _ = await _sold_last_season(db)
        _, their_contact = await _sold_last_season(db)

        with pytest.raises(Exception) as excinfo:
            await QuoteService(db).renew_last_season(mine.id, their_contact.id)

        assert "404" in str(excinfo.value) or "not found" in str(excinfo.value).lower()
        await db.rollback()
