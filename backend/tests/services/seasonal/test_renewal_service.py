"""Renewing one house: the list, and the draft quote it produces.

The bulk pre-booking path is already covered by
``tests/services/prebooking``; what is untested until here is the *single*
customer motion — pick last season's house, get this season's draft with last
season's work already on it.

The cases that matter are the ones a naive "copy the quote" gets wrong:

* a Christmas sale provisions **two** plan rows (install + takedown) that share
  one quote, so an unaggregated join lists the same house twice;
* ``source_quote_id`` is ``ON DELETE SET NULL``, so a deleted quote leaves a live
  plan with nothing to copy — that must be a clean 404-shaped error, not an empty
  draft that reads like a bug;
* ``service_category`` is snapshotted from the price book and never read from a
  request body, so a plain create drops the seasonal tag and the renewal lands
  untagged — the thing the operator explicitly asked for.

Marked ``integration`` (Postgres: ``DISTINCT ON``, the plan table's partial
unique index). Run with ``-m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

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
from app.services.seasonal.renewal_service import (
    CHRISTMAS_SERVICE_CATEGORY,
    ChristmasRenewalService,
    NoPriorSeasonQuoteError,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Defaults put takedown at Jan 8, so "now" in midsummer 2026 is selling the 2026
# season and anything signed before 2026-01-08 is a prior season.
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


async def _lit_last_season(
    db: AsyncSession,
    workspace: Workspace,
    contact: Contact,
    *,
    signed_at: datetime = LAST_SEASON,
    lines: list[dict[str, Any]] | None = None,
    plan_titles: tuple[str, ...] = ("Christmas Install", "Christmas Takedown"),
) -> Quote:
    """An approved seasonal quote plus the plan rows its approval provisioned."""
    lines = lines or [
        {"name": "C9 Roofline — 180 ft", "unit_price": 1620, "category": "christmas"},
        {"name": "Wrapped trees (3)", "unit_price": 780, "category": "christmas"},
    ]
    quote = Quote(
        workspace_id=workspace.id,
        contact_id=contact.id,
        number=f"QUO-{uuid.uuid4().int % 1_000_000:06d}",
        status="approved",
        currency="USD",
        subtotal=sum(li["unit_price"] for li in lines),
        tax_amount=0,
        discount_amount=0,
        total=sum(li["unit_price"] for li in lines),
        approved_at=signed_at,
    )
    db.add(quote)
    await db.flush()

    for offset, line in enumerate(lines):
        db.add(
            QuoteLineItem(
                quote_id=quote.id,
                name=line["name"],
                quantity=1,
                unit_price=line["unit_price"],
                discount=0,
                total=line["unit_price"],
                service_category=line.get("category"),
                created_at=signed_at + timedelta(seconds=offset),
            )
        )
    # Both plan rows a seasonal approval writes, sharing one quote.
    for title in plan_titles:
        db.add(
            RecurringJobTemplate(
                workspace_id=workspace.id,
                contact_id=contact.id,
                plan_type=str(ServicePlanType.CHRISTMAS_LIGHTS),
                source_quote_id=quote.id,
                title=title,
                frequency=str(RecurrenceFrequency.YEARLY),
                interval=1,
                created_at=signed_at,
                next_run_at=signed_at + timedelta(days=365),
            )
        )
    await db.flush()
    return quote


# --------------------------------------------------------------------------- #
# The list
# --------------------------------------------------------------------------- #
async def test_a_house_lit_last_season_appears_once():
    """Install + takedown plans share a quote; the house is still one row."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        quote = await _lit_last_season(db, ws, contact)

        items, total = await ChristmasRenewalService(db).list_candidates(ws, now=NOW)

        assert total == 1
        assert len(items) == 1
        assert items[0].contact_id == contact.id
        assert items[0].quote_id == quote.id
        assert items[0].contact_name == "Grace Hopper"
        assert items[0].line_item_count == 2
        await db.rollback()


async def test_this_seasons_signup_is_not_offered_for_renewal():
    """Selling the 2026 season, a 2026 signup is a sale, not a renewal."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _lit_last_season(db, ws, contact, signed_at=datetime(2026, 6, 1, tzinfo=UTC))

        _, total = await ChristmasRenewalService(db).list_candidates(ws, now=NOW)

        assert total == 0
        await db.rollback()


async def test_a_repeat_customer_is_keyed_to_their_latest_quote():
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _lit_last_season(
            db, ws, contact, signed_at=TWO_SEASONS_AGO, plan_titles=("Christmas Install 2024",)
        )
        recent = await _lit_last_season(db, ws, contact, signed_at=LAST_SEASON)

        items, total = await ChristmasRenewalService(db).list_candidates(ws, now=NOW)

        assert total == 1
        assert items[0].quote_id == recent.id
        await db.rollback()


async def test_another_workspaces_customers_are_never_listed():
    async with AsyncSessionLocal() as db:
        mine = await _workspace(db)
        theirs = await _workspace(db)
        await _lit_last_season(db, theirs, await _contact(db, theirs.id, "Ada"))

        _, total = await ChristmasRenewalService(db).list_candidates(mine, now=NOW)

        assert total == 0
        await db.rollback()


async def test_search_matches_the_customer_name():
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _lit_last_season(db, ws, await _contact(db, ws.id, "Grace"))
        await _lit_last_season(db, ws, await _contact(db, ws.id, "Ada"))

        items, total = await ChristmasRenewalService(db).list_candidates(ws, search="ada", now=NOW)

        assert total == 1
        assert items[0].contact_name.startswith("Ada")
        await db.rollback()


# --------------------------------------------------------------------------- #
# The draft it produces
# --------------------------------------------------------------------------- #
async def test_renewal_copies_last_seasons_lines_onto_a_new_draft():
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        source = await _lit_last_season(db, ws, contact)

        created = await ChristmasRenewalService(db).create_renewal_quote(ws, contact.id, now=NOW)

        assert created.id != source.id
        assert created.status == "draft"
        assert created.contact_id == contact.id
        assert [li.name for li in created.line_items] == [
            "C9 Roofline — 180 ft",
            "Wrapped trees (3)",
        ]
        assert [float(li.unit_price) for li in created.line_items] == [1620.0, 780.0]
        await db.rollback()


async def test_renewed_lines_keep_the_seasonal_tag():
    """The whole point of "tagged like a Christmas job"."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _lit_last_season(db, ws, contact)

        created = await ChristmasRenewalService(db).create_renewal_quote(ws, contact.id, now=NOW)

        assert {li.service_category for li in created.line_items} == {"christmas"}
        await db.rollback()


async def test_an_untagged_old_line_still_renews_as_seasonal():
    """A quote from before category snapshotting must not renew untagged."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _lit_last_season(
            db,
            ws,
            contact,
            lines=[{"name": "Roofline", "unit_price": 900, "category": None}],
        )

        created = await ChristmasRenewalService(db).create_renewal_quote(ws, contact.id, now=NOW)

        assert created.line_items[0].service_category == CHRISTMAS_SERVICE_CATEGORY
        await db.rollback()


async def test_the_draft_is_titled_for_the_season_being_sold():
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _lit_last_season(db, ws, contact)

        created = await ChristmasRenewalService(db).create_renewal_quote(ws, contact.id, now=NOW)

        assert created.title == "2026 Christmas Lights — Renewal"
        await db.rollback()


async def test_a_contact_with_no_prior_season_cannot_be_renewed():
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)

        with pytest.raises(NoPriorSeasonQuoteError):
            await ChristmasRenewalService(db).create_renewal_quote(ws, contact.id, now=NOW)
        await db.rollback()


async def test_another_workspaces_contact_cannot_be_renewed():
    """Tenant isolation on the write path, not just the list."""
    async with AsyncSessionLocal() as db:
        mine = await _workspace(db)
        theirs = await _workspace(db)
        their_contact = await _contact(db, theirs.id, "Ada")
        await _lit_last_season(db, theirs, their_contact)

        with pytest.raises(NoPriorSeasonQuoteError):
            await ChristmasRenewalService(db).create_renewal_quote(mine, their_contact.id, now=NOW)
        await db.rollback()
