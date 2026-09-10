"""Who the Renew Last Season's Homes screen offers.

The per-customer rebuild is covered by ``test_christmas_renewal_quote``. What is
untested until here is the *list* that screen is built on, and specifically the
two ways a naive query gets it wrong:

* a seasonal sale provisions **two** plan rows (install + takedown) sharing one
  quote, so an unaggregated join shows the same house twice;
* the list is scoped to a workspace, and a stale contact id must never widen it.

Marked ``integration`` (Postgres: ``DISTINCT ON``, ``LATERAL``, and the plan
table's partial unique index). Run with ``-m integration``.
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
from app.models.quote import Quote
from app.models.recurring_job import (
    RecurrenceFrequency,
    RecurringJobTemplate,
    ServicePlanType,
)
from app.models.workspace import Workspace
from app.services.seasonal.renewal_candidates import list_renewal_candidates

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Takedown defaults to Jan 8, so "now" in midsummer 2026 sells the 2026 season
# and anything signed before 2026-01-08 belongs to a prior one.
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
LAST_SEASON = datetime(2025, 11, 20, 12, 0, tzinfo=UTC)
TWO_SEASONS_AGO = datetime(2024, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Renewals",
        slug=f"renew-{uuid.uuid4().hex[:8]}",
        settings={"pricing": {"christmas": {"enabled": True}}},
    )
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db: AsyncSession, workspace_id: uuid.UUID, name: str = "Grace") -> Contact:
    email = f"{name.lower()}-{uuid.uuid4().hex[:6]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name=name,
        last_name="Hopper",
        email=email,
        email_hash=hash_value(email),
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _lit(
    db: AsyncSession,
    workspace: Workspace,
    contact: Contact,
    *,
    signed_at: datetime = LAST_SEASON,
    total: float = 2400,
    with_quote: bool = True,
    plan_titles: tuple[str, ...] = ("Christmas Install", "Christmas Takedown"),
) -> Quote | None:
    """A sold seasonal job: the approved quote plus the plan rows it provisioned."""
    quote = None
    if with_quote:
        quote = Quote(
            workspace_id=workspace.id,
            contact_id=contact.id,
            number=f"QUO-{uuid.uuid4().int % 1_000_000:06d}",
            status="approved",
            primary_service="christmas_lights",
            currency="USD",
            subtotal=total,
            tax_amount=0,
            discount_amount=0,
            total=total,
            created_at=signed_at,
            approved_at=signed_at,
        )
        db.add(quote)
        await db.flush()

    for title in plan_titles:
        db.add(
            RecurringJobTemplate(
                workspace_id=workspace.id,
                contact_id=contact.id,
                plan_type=str(ServicePlanType.CHRISTMAS_LIGHTS),
                source_quote_id=quote.id if quote else None,
                title=title,
                frequency=str(RecurrenceFrequency.YEARLY),
                interval=1,
                created_at=signed_at,
                next_run_at=signed_at + timedelta(days=365),
            )
        )
    await db.flush()
    return quote


async def test_a_house_lit_last_season_appears_exactly_once():
    """Install + takedown plans share one quote; the house is still one row."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        quote = await _lit(db, ws, contact)

        items, total, season_year = await list_renewal_candidates(db, ws, now=NOW)

        assert total == 1
        assert len(items) == 1
        assert items[0].contact_id == contact.id
        assert items[0].contact_name == "Grace Hopper"
        assert items[0].quote_number == quote.number
        assert items[0].quote_total == 2400
        assert season_year == 2026
        await db.rollback()


async def test_this_seasons_signup_is_a_sale_not_a_renewal():
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _lit(db, ws, contact, signed_at=datetime(2026, 6, 1, tzinfo=UTC))

        _, total, _ = await list_renewal_candidates(db, ws, now=NOW)

        assert total == 0
        await db.rollback()


async def test_a_repeat_customer_shows_their_most_recent_season():
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _lit(
            db,
            ws,
            contact,
            signed_at=TWO_SEASONS_AGO,
            total=1000,
            plan_titles=("Christmas Install 2024",),
        )
        recent = await _lit(db, ws, contact, signed_at=LAST_SEASON, total=2400)

        items, total, _ = await list_renewal_candidates(db, ws, now=NOW)

        assert total == 1
        assert items[0].quote_number == recent.number
        assert items[0].signed_up_at == LAST_SEASON
        await db.rollback()


async def test_another_workspaces_customers_are_never_listed():
    async with AsyncSessionLocal() as db:
        mine = await _workspace(db)
        theirs = await _workspace(db)
        await _lit(db, theirs, await _contact(db, theirs.id, "Ada"))

        _, total, _ = await list_renewal_candidates(db, mine, now=NOW)

        assert total == 0
        await db.rollback()


async def test_a_customer_whose_quote_was_deleted_is_still_renewable():
    """The plan row is the eligibility signal; the quote is only the subtitle.

    ``source_quote_id`` is ON DELETE SET NULL, so deleting an old quote leaves a
    live plan. Dropping that customer would hide a real past customer; showing
    them with no number lets the rep decide.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _lit(db, ws, contact, with_quote=False)

        items, total, _ = await list_renewal_candidates(db, ws, now=NOW)

        assert total == 1
        assert items[0].contact_id == contact.id
        assert items[0].quote_number is None
        assert items[0].quote_total is None
        await db.rollback()


async def test_search_matches_the_customer_name():
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _lit(db, ws, await _contact(db, ws.id, "Grace"))
        await _lit(db, ws, await _contact(db, ws.id, "Ada"))

        items, total, _ = await list_renewal_candidates(db, ws, search="ada", now=NOW)

        assert total == 1
        assert items[0].contact_name.startswith("Ada")
        await db.rollback()


async def test_search_matches_the_quote_number():
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        quote = await _lit(db, ws, contact)
        await _lit(db, ws, await _contact(db, ws.id, "Ada"))

        items, total, _ = await list_renewal_candidates(db, ws, search=quote.number, now=NOW)

        assert total == 1
        assert items[0].contact_id == contact.id
        await db.rollback()


async def test_the_page_is_capped_but_the_total_is_not():
    """The screen pages; the count tells the rep how much warm list is left."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        for i in range(3):
            await _lit(
                db,
                ws,
                await _contact(db, ws.id, f"Cust{i}"),
                signed_at=LAST_SEASON - timedelta(days=i),
            )

        items, total, _ = await list_renewal_candidates(db, ws, limit=2, now=NOW)

        assert total == 3
        assert len(items) == 2
        # Newest signup first.
        assert items[0].signed_up_at > items[1].signed_up_at
        await db.rollback()
