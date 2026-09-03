"""Integration tests for :class:`app.services.upsell.UpsellService`.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

These are the security tests for the on-site upsell surface. The ``field`` tier
holds neither ``crm:read`` nor ``billing:read``, so this service is the *only*
path a technician has to a customer record or a price, and every assertion here
is about that path staying narrow:

* a technician sees only jobs assigned to them (or routed to their crew);
* another technician's job is a 404, never a 403 (no id-enumeration oracle);
* the add-on menu excludes non-attachable and archived items;
* prices come from the price book, not the request;
* a valid job id cannot be paired with an unrelated quote id to deliver it.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.models.catalog import CatalogItem
from app.models.contact import Contact
from app.models.field_service import Crew, Job, JobAssignment, JobStatus, Technician
from app.models.quote import Quote
from app.models.recurring_job import ServicePlanType
from app.models.workspace import Workspace
from app.schemas.upsell import (
    UpsellCarePlanSelection,
    UpsellCustomQuoteLine,
    UpsellQuoteLine,
    UpsellQuoteRequest,
)
from app.services.field_service.exceptions import JobNotFoundError
from app.services.quotes import proposal_pricing as pp
from app.services.quotes.pricing_config import get_pricing_config
from app.services.quotes.quote_service import QuoteService
from app.services.recurring_jobs.service_plan_provisioner import ServicePlanProvisioner
from app.services.upsell import UpsellService
from app.services.upsell.exceptions import (
    UpsellCarePlanUnavailableError,
    UpsellItemNotAttachableError,
    UpsellNoLineItemsError,
    UpsellNotASellerError,
    UpsellProposalLimitError,
    UpsellQuoteNotForJobError,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

FIELD = "technician"
LEAD = "lead_technician"
ADMIN = "admin"

# A workspace that caps what a plain technician may sell on site.
LIMIT_PRICING = {
    "pricing": {
        "financing": {"enabled": False},
        "upsell": {"field_proposal_limit": 500},
    }
}


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the asyncpg pool around each test to avoid closed-loop reuse."""
    await engine.dispose()
    yield
    await engine.dispose()


# A workspace's Care Plan tiers live in ``settings.pricing``. Mirrors the shape
# ``scripts/demo/seed_lighting_workspace.py`` seeds.
# A retained legacy buffer proves old settings cannot alter direct selling prices.
BUFFER_PRICING = {"pricing": {"financing": {"enabled": True, "fee_buffer": 0.11}}}

CARE_PLAN_PRICING = {
    "pricing": {
        "care_plan": {
            "free_fixtures": 10,
            "tiers": [
                {
                    "key": "essential",
                    "name": "Essential",
                    "base": 179,
                    "per_fixture": 15,
                    "visits": 1,
                },
                {
                    "key": "gold",
                    "name": "Gold",
                    "base": 359,
                    "per_fixture": 22,
                    "visits": 4,
                    "repair_discount": 0.15,
                },
            ],
        }
    }
}


async def _workspace(db, *, settings: dict | None = None) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Lights",
        slug=f"lights-{uuid.uuid4().hex[:8]}",
        settings=settings,
    )
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, ws: Workspace, name: str = "Dana") -> Contact:
    contact = Contact(
        workspace_id=ws.id,
        first_name=name,
        last_name="Homeowner",
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _technician(db, ws: Workspace, user_id: int, crew: Crew | None = None) -> Technician:
    tech = Technician(
        workspace_id=ws.id,
        user_id=user_id,
        name=f"Tech {user_id}",
        crew_id=crew.id if crew else None,
    )
    db.add(tech)
    await db.flush()
    return tech


async def _job(db, ws: Workspace, contact: Contact, *, crew: Crew | None = None) -> Job:
    job = Job(
        workspace_id=ws.id,
        contact_id=contact.id,
        title="Pressure wash",
        status=JobStatus.SCHEDULED,
        crew_id=crew.id if crew else None,
    )
    db.add(job)
    await db.flush()
    return job


async def _assign(db, job: Job, tech: Technician) -> None:
    db.add(JobAssignment(job_id=job.id, technician_id=tech.id))
    await db.flush()


async def _catalog_item(
    db,
    ws: Workspace,
    *,
    name: str = "Landscape lighting",
    price: float = 2400.0,
    attachable: bool = True,
    active: bool = True,
    targets: list[str] | None = None,
    attributes: dict | None = None,
) -> CatalogItem:
    item = CatalogItem(
        workspace_id=ws.id,
        name=name,
        unit_price=price,
        is_attachable=attachable,
        is_active=active,
        attach_targets=targets or [],
        service_category="landscape",
        attributes=attributes,
    )
    db.add(item)
    await db.flush()
    return item


# --------------------------------------------------------------------------- #
# Job scoping — the boundary the whole feature rests on
# --------------------------------------------------------------------------- #
async def test_technician_sees_only_their_assigned_job() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        mine, theirs = await _contact(db, ws, "Mine"), await _contact(db, ws, "Theirs")
        tech = await _technician(db, ws, user_id=1)
        other = await _technician(db, ws, user_id=2)
        my_job, their_job = await _job(db, ws, mine), await _job(db, ws, theirs)
        await _assign(db, my_job, tech)
        await _assign(db, their_job, other)

        listed = await UpsellService(db).list_jobs(ws.id, 1, LEAD)
        assert [job.id for job in listed.items] == [my_job.id]
        assert listed.total == 1


async def test_crew_routed_job_is_visible_without_a_direct_assignment() -> None:
    """Matches the calendar's rule: tagged to them OR routed to their crew."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        crew = Crew(workspace_id=ws.id, name="Night crew")
        db.add(crew)
        await db.flush()
        contact = await _contact(db, ws)
        await _technician(db, ws, user_id=1, crew=crew)
        job = await _job(db, ws, contact, crew=crew)

        listed = await UpsellService(db).list_jobs(ws.id, 1, LEAD)
        assert [row.id for row in listed.items] == [job.id]


async def test_another_technicians_job_is_404_not_403() -> None:
    """A 403 would confirm the id exists and make this an enumeration oracle."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        await _technician(db, ws, user_id=1)
        other = await _technician(db, ws, user_id=2)
        their_job = await _job(db, ws, contact)
        await _assign(db, their_job, other)

        with pytest.raises(JobNotFoundError):
            await UpsellService(db).job_customer(ws.id, their_job.id, 1, LEAD)


async def test_login_without_a_technician_record_owns_nothing() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        job = await _job(db, ws, contact)

        service = UpsellService(db)
        # Listing is a normal empty state, not an error…
        assert (await service.list_jobs(ws.id, 999, LEAD)).total == 0
        # …but reaching for a specific job still fails closed.
        with pytest.raises(JobNotFoundError):
            await service.job_customer(ws.id, job.id, 999, LEAD)


async def test_cross_workspace_job_is_invisible_even_to_an_admin() -> None:
    async with AsyncSessionLocal() as db:
        ws, other_ws = await _workspace(db), await _workspace(db)
        contact = await _contact(db, other_ws)
        foreign_job = await _job(db, other_ws, contact)

        with pytest.raises(JobNotFoundError):
            await UpsellService(db).job_customer(ws.id, foreign_job.id, 1, ADMIN)


async def test_billing_writer_is_not_job_scoped() -> None:
    """Managers can already quote anyone via the quotes API; no scoping theatre."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        job = await _job(db, ws, contact)  # assigned to nobody

        customer = await UpsellService(db).job_customer(ws.id, job.id, 1, ADMIN)
        assert customer.contact_id == contact.id


async def test_customer_projection_is_narrow() -> None:
    """The technician gets door-and-address detail, not the CRM record."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        customer = await UpsellService(db).job_customer(ws.id, job.id, 1, LEAD)
        assert customer.full_name == "Dana Homeowner"
        exposed = customer.model_dump().keys()
        for leaked in ("lifecycle_stage", "notes", "tags", "lead_source_id", "owner_id"):
            assert leaked not in exposed


# --------------------------------------------------------------------------- #
# Catalog scoping — the add-on menu, not the price book
# --------------------------------------------------------------------------- #
async def test_catalog_excludes_non_attachable_and_archived_items() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        addon = await _catalog_item(db, ws, name="Path lights")
        await _catalog_item(db, ws, name="Full roof replacement", attachable=False)
        await _catalog_item(db, ws, name="Discontinued bulb", active=False)

        listed = await UpsellService(db).list_attachable_catalog(ws.id)
        assert [item.name for item in listed.items] == ["Path lights"]
        assert listed.items[0].id == addon.id


async def test_catalog_attach_target_filter_is_case_insensitive() -> None:
    """``attach_targets`` is operator-typed free text, so 'Wash' must match 'wash'."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _catalog_item(db, ws, name="Lighting", targets=["Wash"])
        await _catalog_item(db, ws, name="Gutter guard", targets=["gutters"])

        listed = await UpsellService(db).list_attachable_catalog(ws.id, attach_target="wash")
        assert [item.name for item in listed.items] == ["Lighting"]


async def test_catalog_item_with_no_targets_is_unrestricted() -> None:
    """Empty ``attach_targets`` means 'no restriction recorded', per the column."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _catalog_item(db, ws, name="Anything goes", targets=[])

        listed = await UpsellService(db).list_attachable_catalog(ws.id, attach_target="roof")
        assert [item.name for item in listed.items] == ["Anything goes"]


async def test_per_foot_rate_is_labelled_so_it_cannot_read_as_a_job_total() -> None:
    """A rate and a total must not render identically on the technician's menu.

    The real price book stores string lighting at a per-linear-foot rate (see
    ``scripts/demo/seed_lighting_workspace.py``). Unlabelled, "$18.50" is the
    number a technician says out loud for a patio that prices out near $900.

    The item's job *minimum* is deliberately not surfaced: minimums apply to
    whole-system quotes, not to the upgrades this screen sells.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _catalog_item(
            db,
            ws,
            name="Bistro lights",
            price=18.50,
            attributes={"per_linear_foot": True, "minimum": 2307},
        )
        await _catalog_item(db, ws, name="Flat fixture", price=640.0)

        listed = await UpsellService(db).list_attachable_catalog(ws.id)
        by_name = {item.name: item for item in listed.items}
        assert by_name["Bistro lights"].price_unit == "per linear foot"
        # A flat-priced item must stay unlabelled rather than gain a fake unit.
        assert by_name["Flat fixture"].price_unit is None


async def test_malformed_attributes_degrade_instead_of_breaking_the_menu() -> None:
    """``attributes`` is operator-authored JSONB, so junk must not 500 the menu."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _catalog_item(
            db,
            ws,
            name="Sloppy import",
            attributes={"per_linear_foot": False, "unrelated": {"nested": [1, 2]}},
        )

        listed = await UpsellService(db).list_attachable_catalog(ws.id)
        assert listed.items[0].price_unit is None


async def test_a_truthy_flag_labels_the_rate_even_when_it_is_not_a_real_bool() -> None:
    """Permissive on purpose — the two failure directions are not symmetric.

    An importer writing ``"true"`` instead of ``true`` should still get the label.
    Over-labelling a flat price reads as an odd unit; *under*-labelling a per-foot
    rate is the one that makes a technician quote $18.50 for a $900 patio.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _catalog_item(db, ws, name="Stringy flag", attributes={"per_linear_foot": "true"})

        listed = await UpsellService(db).list_attachable_catalog(ws.id)
        assert listed.items[0].price_unit == "per linear foot"


# --------------------------------------------------------------------------- #
# Quote creation — server-side pricing
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Direct selling prices — legacy buffers never change the price book
# --------------------------------------------------------------------------- #
async def test_menu_uses_the_configured_selling_price() -> None:
    """The catalog amount is the customer price on every selling surface."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=BUFFER_PRICING)
        await _catalog_item(db, ws, name="ZDC Color Uplight", price=785.0)

        listed = await UpsellService(db).list_attachable_catalog(ws.id)
        assert listed.items[0].unit_price == 785.0


async def test_quoted_price_matches_the_menu_price_the_technician_read_aloud() -> None:
    """Menu and proposal must agree, or the tech quotes a number that then changes."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=BUFFER_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="ZDC Color Uplight", price=785.0)

        service = UpsellService(db)
        menu_price = (await service.list_attachable_catalog(ws.id)).items[0].unit_price
        quote = await service.create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=2)]),
            user_id=1,
            role=LEAD,
        )

        assert menu_price == 785.0
        assert quote.line_items[0].unit_price == menu_price
        assert quote.total == 1570.0


async def test_technician_price_equals_the_wizards_price_for_the_same_item() -> None:
    """A fixture quoted in a driveway must match one quoted from the office."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=BUFFER_PRICING)
        await _catalog_item(db, ws, name="ZD Uplight", price=411.0)

        listed = await UpsellService(db).list_attachable_catalog(ws.id)
        config = get_pricing_config(ws)
        assert listed.items[0].unit_price == float(pp.gross_up_price(411.0, config))


async def test_legacy_commission_setting_does_not_increase_the_price() -> None:
    """Stored commission settings remain compatible but are internal costs."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(
            db,
            settings={
                "pricing": {
                    "financing": {"enabled": True, "fee_buffer": 0.11},
                    "commission": {"enabled": True, "in_price": True, "rate": 0.10},
                }
            },
        )
        await _catalog_item(db, ws, name="ZDC Color Uplight", price=785.0)

        listed = await UpsellService(db).list_attachable_catalog(ws.id)
        assert listed.items[0].unit_price == 785.0


async def test_zero_buffer_workspace_sells_at_the_book_price() -> None:
    """Disabled legacy financing also preserves the configured selling price."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(
            db, settings={"pricing": {"financing": {"enabled": False, "fee_buffer": 0.11}}}
        )
        await _catalog_item(db, ws, name="Flat rate service", price=320.0)

        listed = await UpsellService(db).list_attachable_catalog(ws.id)
        assert listed.items[0].unit_price == 320.0


async def test_quote_prices_come_from_the_catalog_not_the_request() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Landscape lighting", price=2400.0)
        item.sku = "LIGHT-KIT"
        item.components = [
            {"sku": "PATH-12V", "description": "Path-light fixture", "qty": 4},
            {"sku": "BULB-LED", "description": "Warm LED bulb", "qty": 4},
        ]

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=2)]),
            user_id=1,
            role=LEAD,
        )
        assert len(quote.line_items) == 1
        line = quote.line_items[0]
        assert line.name == "Landscape lighting"
        # The catalog price is authoritative; request-supplied numbers are ignored.
        assert line.unit_price == 2400.0
        assert line.total == 4800.0
        # Attributed to the technician so attach-rate reporting can pay the spiff.
        assert quote.contact_id == contact.id
        # Field orders collect the full one-time total on the customer's device.
        assert quote.deposit_percentage == 100
        assert quote.deposit_amount == 4800.0
        assert quote.deposit_required is True
        # BOM quantities scale by the quoted catalog quantity and stay internal.
        assert quote.proposal_document is not None
        assert quote.proposal_document["fulfillment"] == [
            {"sku": "PATH-12V", "description": "Path-light fixture", "qty": 8.0},
            {"sku": "BULB-LED", "description": "Warm LED bulb", "qty": 8.0},
        ]

        with patch(
            "app.services.quotes.quote_service.notify_workspace_event",
            new_callable=AsyncMock,
        ) as notify:
            approved = await QuoteService(db).approve_quote(ws.id, quote.id)

        assert approved.status == "approved"
        notify.assert_awaited_once()
        assert notify.await_args.kwargs["email_details"] == {
            "PATH-12V": "Qty 8 — Path-light fixture",
            "BULB-LED": "Qty 8 — Warm LED bulb",
        }


async def test_quote_accepts_a_capped_custom_line_item() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(
                custom_line_items=[
                    UpsellCustomQuoteLine(name="  Lift rental  ", quantity=3, unit_price=75.0)
                ]
            ),
            user_id=1,
            role=LEAD,
        )

        assert quote.total == 225.0
        assert len(quote.line_items) == 1
        assert quote.line_items[0].name == "Lift rental"
        assert quote.line_items[0].quantity == 3
        assert quote.line_items[0].unit_price == 75.0
        assert quote.deposit_percentage == 100
        assert quote.deposit_amount == 225.0
        assert quote.proposal_document is not None
        assert quote.proposal_document["fulfillment"] == [
            {
                "sku": "Lift rental",
                "description": "Custom line item — confirm sourcing requirements",
                "qty": 3.0,
            }
        ]


async def test_quote_rejects_a_non_attachable_item() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        forbidden = await _catalog_item(db, ws, name="Roof replacement", attachable=False)

        with pytest.raises(UpsellItemNotAttachableError):
            await UpsellService(db).create_quote(
                ws.id,
                job.id,
                UpsellQuoteRequest(
                    line_items=[UpsellQuoteLine(catalog_item_id=forbidden.id, quantity=1)]
                ),
                user_id=1,
                role=LEAD,
            )


async def test_quote_rejects_another_workspaces_catalog_item() -> None:
    async with AsyncSessionLocal() as db:
        ws, other_ws = await _workspace(db), await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        foreign_item = await _catalog_item(db, other_ws, name="Their lighting")

        with pytest.raises(UpsellItemNotAttachableError):
            await UpsellService(db).create_quote(
                ws.id,
                job.id,
                UpsellQuoteRequest(
                    line_items=[UpsellQuoteLine(catalog_item_id=foreign_item.id, quantity=1)]
                ),
                user_id=1,
                role=LEAD,
            )


async def test_quote_on_someone_elses_job_is_refused() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        await _technician(db, ws, user_id=1)
        other = await _technician(db, ws, user_id=2)
        their_job = await _job(db, ws, contact)
        await _assign(db, their_job, other)
        item = await _catalog_item(db, ws)

        with pytest.raises(JobNotFoundError):
            await UpsellService(db).create_quote(
                ws.id,
                their_job.id,
                UpsellQuoteRequest(
                    line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=1)]
                ),
                user_id=1,
                role=LEAD,
            )


async def test_empty_proposal_is_refused() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        with pytest.raises(UpsellNoLineItemsError):
            await UpsellService(db).create_quote(
                ws.id, job.id, UpsellQuoteRequest(line_items=[]), user_id=1, role=LEAD
            )


# --------------------------------------------------------------------------- #
# Selling KPIs — a technician's own numbers, never a colleague's
# --------------------------------------------------------------------------- #
RANK_PRICING = {
    "pricing": {
        "financing": {"enabled": False},
        "upsell": {
            "ranks": [
                # Deliberately out of order: the config sorts them.
                {"key": "gold", "name": "Gold", "threshold": 10000, "reward": "$500 bonus"},
                {"key": "bronze", "name": "Bronze", "threshold": 2000, "reward": "$100 bonus"},
                {"key": "silver", "name": "Silver", "threshold": 5000, "reward": "$250 bonus"},
            ]
        },
    }
}


async def _sold_quote(
    db, ws: Workspace, contact: Contact, *, user_id: int, total: float, status: str = "approved"
) -> Quote:
    quote = Quote(
        workspace_id=ws.id,
        contact_id=contact.id,
        number=f"QUO-{uuid.uuid4().hex[:6]}",
        title="Add-on",
        status=status,
        total=total,
        created_by_id=user_id,
    )
    db.add(quote)
    await db.flush()
    return quote


async def test_my_stats_counts_only_the_callers_own_proposals() -> None:
    """The isolation guarantee: a technician never sees a colleague's revenue."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        await _sold_quote(db, ws, contact, user_id=1, total=1200.0)
        await _sold_quote(db, ws, contact, user_id=2, total=9999.0)

        stats = await UpsellService(db).my_selling_stats(ws.id, 1)
        assert stats.revenue_approved == 1200.0
        assert stats.proposals_approved == 1


async def test_my_stats_ignores_drafts_and_other_workspaces() -> None:
    async with AsyncSessionLocal() as db:
        ws, other = await _workspace(db), await _workspace(db)
        contact = await _contact(db, ws)
        other_contact = await _contact(db, other)
        await _sold_quote(db, ws, contact, user_id=1, total=500.0, status="draft")
        await _sold_quote(db, other, other_contact, user_id=1, total=800.0)

        stats = await UpsellService(db).my_selling_stats(ws.id, 1)
        assert stats.proposals_sent == 0
        assert stats.revenue_approved == 0


async def test_my_stats_close_rate_is_null_not_zero_when_nothing_was_sent() -> None:
    """A quiet month must not render as a 0% close rate."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        stats = await UpsellService(db).my_selling_stats(ws.id, 1)
        assert stats.proposals_sent == 0
        assert stats.close_rate is None


async def test_my_stats_close_rate_and_care_plan_count() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        approved = await _sold_quote(db, ws, contact, user_id=1, total=1000.0)
        approved.proposal_document = {"care_plan": {"selected": "gold"}}
        await _sold_quote(db, ws, contact, user_id=1, total=400.0, status="declined")
        await db.flush()

        stats = await UpsellService(db).my_selling_stats(ws.id, 1)
        assert stats.proposals_sent == 2
        assert stats.proposals_approved == 1
        assert stats.close_rate == 0.5
        assert stats.care_plans_sold == 1


async def test_no_configured_ranks_means_no_ladder_not_an_invented_one() -> None:
    """Rank names and payouts are an operator's comp policy, never a default."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        await _sold_quote(db, ws, contact, user_id=1, total=50000.0)

        stats = await UpsellService(db).my_selling_stats(ws.id, 1)
        # The facts still report; only the ladder is absent.
        assert stats.revenue_approved == 50000.0
        assert stats.rank is None


async def test_rank_progress_is_measured_from_the_current_rung() -> None:
    """Just-ranked-up must read as near-empty toward the next rung, not near-full."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=RANK_PRICING)
        contact = await _contact(db, ws)
        # 2,600 — just past Bronze (2,000), chasing Silver (5,000).
        await _sold_quote(db, ws, contact, user_id=1, total=2600.0)

        rank = (await UpsellService(db).my_selling_stats(ws.id, 1)).rank
        assert rank is not None
        assert rank.current_name == "Bronze"
        assert rank.next_name == "Silver"
        assert rank.amount_to_next == 2400.0
        # 600 of the 3,000 between Bronze and Silver — not 2600/5000.
        assert rank.progress == 0.2


async def test_rank_below_the_first_rung_still_shows_the_target() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=RANK_PRICING)
        contact = await _contact(db, ws)
        await _sold_quote(db, ws, contact, user_id=1, total=500.0)

        rank = (await UpsellService(db).my_selling_stats(ws.id, 1)).rank
        assert rank is not None
        assert rank.current_name is None
        assert rank.next_name == "Bronze"
        assert rank.progress == 0.25
        assert rank.next_reward == "$100 bonus"


async def test_top_rank_has_no_next_target() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=RANK_PRICING)
        contact = await _contact(db, ws)
        await _sold_quote(db, ws, contact, user_id=1, total=12000.0)

        rank = (await UpsellService(db).my_selling_stats(ws.id, 1)).rank
        assert rank is not None
        assert rank.current_name == "Gold"
        assert rank.current_reward == "$500 bonus"
        assert rank.next_name is None
        assert rank.amount_to_next is None


async def test_ranks_are_sorted_however_the_operator_entered_them() -> None:
    """RANK_PRICING lists Gold first; the ladder must still count upwards."""
    from app.schemas.pricing import PricingSettings

    config = PricingSettings.model_validate(RANK_PRICING["pricing"])
    assert [rank.name for rank in config.upsell.ranks] == ["Bronze", "Silver", "Gold"]


# --------------------------------------------------------------------------- #
# Who may sell at all — a plain technician does not quote, they escalate
# --------------------------------------------------------------------------- #
async def test_a_plain_technician_cannot_create_a_proposal() -> None:
    """The business rule, enforced in the service and not only in the router.

    A technician holds no ``upsell:sell``, so ``CanUpsell`` already 403s them at
    the edge. This pins the same answer one layer down, where a future caller
    (a job-completion hook, a script) could otherwise sell as a technician by
    forgetting the dependency.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Uplighting", price=120.0)

        with pytest.raises(UpsellNotASellerError):
            await UpsellService(db).create_quote(
                ws.id,
                job.id,
                UpsellQuoteRequest(
                    line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=1)]
                ),
                user_id=1,
                role=FIELD,
            )


async def test_a_plain_technician_cannot_deliver_a_proposal() -> None:
    """Refused on the way out too, not just on the way in."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Uplighting", price=120.0)

        service = UpsellService(db)
        quote = await service.create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=1)]),
            user_id=1,
            role=LEAD,
        )

        # The lead built it; the technician must still not be able to send it.
        with pytest.raises(UpsellNotASellerError):
            await service.deliver_quote(
                ws.id,
                job.id,
                quote.id,
                channel="sms",
                user_id=1,
                role=FIELD,
            )


async def test_lead_can_present_the_job_quote_in_person_without_delivery() -> None:
    """Publishing allocates an approval link but never needs a phone or email."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="LED bulb replacement", price=20.0)

        service = UpsellService(db)
        quote = await service.create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=3)]),
            user_id=1,
            role=LEAD,
        )

        presented = await service.present_quote(
            ws.id,
            job.id,
            quote.id,
            user_id=1,
            role=LEAD,
        )

        assert presented.status == "sent"
        assert presented.public_token

        with pytest.raises(UpsellNotASellerError):
            await service.present_quote(
                ws.id,
                job.id,
                quote.id,
                user_id=1,
                role=FIELD,
            )


async def test_an_unknown_role_cannot_sell() -> None:
    """Fail-closed: a corrupt or legacy role string lands on the field tier."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Uplighting", price=120.0)

        with pytest.raises(UpsellNotASellerError):
            await UpsellService(db).create_quote(
                ws.id,
                job.id,
                UpsellQuoteRequest(
                    line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=1)]
                ),
                user_id=1,
                role="wizard",
            )


# --------------------------------------------------------------------------- #
# The on-site proposal limit — the ceiling on what a crew lead commits alone
# --------------------------------------------------------------------------- #
async def test_crew_lead_is_refused_past_the_workspace_limit() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=LIMIT_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Uplighting", price=640.0)

        with pytest.raises(UpsellProposalLimitError) as excinfo:
            await UpsellService(db).create_quote(
                ws.id,
                job.id,
                UpsellQuoteRequest(
                    line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=1)]
                ),
                user_id=1,
                role=LEAD,
            )

        # The message has to tell the person standing in the yard what to do,
        # and that person IS the crew lead — so it cannot tell them to go find
        # one.
        message = str(excinfo.value)
        assert "$640.00" in message
        assert "$500.00" in message
        assert "the office" in message
        assert "lead tech" not in message


async def test_custom_lines_count_toward_the_workspace_limit() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=LIMIT_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        with pytest.raises(UpsellProposalLimitError):
            await UpsellService(db).create_quote(
                ws.id,
                job.id,
                UpsellQuoteRequest(
                    custom_line_items=[
                        UpsellCustomQuoteLine(
                            name="Custom fixture labor",
                            quantity=2,
                            unit_price=275.0,
                        )
                    ]
                ),
                user_id=1,
                role=LEAD,
            )


async def test_an_office_tier_sells_the_same_basket_freely() -> None:
    """The limit is a field control, not a company-wide one."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=LIMIT_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Uplighting", price=640.0)

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=4)]),
            user_id=1,
            role=ADMIN,
        )
        assert quote.total == 2560.0


async def test_limit_counts_the_whole_basket_not_the_line() -> None:
    """Four $200 add-ons is an $800 proposal, however it is split up."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=LIMIT_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Path light", price=200.0)

        with pytest.raises(UpsellProposalLimitError):
            await UpsellService(db).create_quote(
                ws.id,
                job.id,
                UpsellQuoteRequest(
                    line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=4)]
                ),
                user_id=1,
                role=LEAD,
            )


async def test_a_basket_exactly_on_the_limit_is_allowed() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=LIMIT_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Path light", price=250.0)

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=2)]),
            user_id=1,
            role=LEAD,
        )
        assert quote.total == 500.0


async def test_legacy_buffer_does_not_push_direct_price_past_the_limit() -> None:
    """A configured $460 selling price remains below the $500 field cap."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(
            db,
            settings={
                "pricing": {
                    "financing": {"enabled": True, "fee_buffer": 0.11},
                    "upsell": {"field_proposal_limit": 500},
                }
            },
        )
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Borderline", price=460.0)

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=1)]),
            user_id=1,
            role=LEAD,
        )

        assert quote.total == 460.0


async def test_no_configured_limit_means_no_cap() -> None:
    """Opt-in: a workspace that never asked for a limit is unaffected."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings={"pricing": {"financing": {"enabled": False}}})
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Big package", price=9000.0)

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=1)]),
            user_id=1,
            role=LEAD,
        )
        assert quote.total == 9000.0


async def test_a_refused_proposal_leaves_no_orphaned_draft() -> None:
    """``create_quote`` commits, so the limit must be checked before it runs."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=LIMIT_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Uplighting", price=640.0)

        with pytest.raises(UpsellProposalLimitError):
            await UpsellService(db).create_quote(
                ws.id,
                job.id,
                UpsellQuoteRequest(
                    line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=1)]
                ),
                user_id=1,
                role=LEAD,
            )

        remaining = (
            (await db.execute(select(Quote).where(Quote.workspace_id == ws.id))).scalars().all()
        )
        assert remaining == []


async def test_a_care_plan_does_not_count_against_the_limit() -> None:
    """Retention is what every technician should be closing; it is not capital."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(
            db,
            settings={
                "pricing": {
                    "financing": {"enabled": False},
                    "upsell": {"field_proposal_limit": 100},
                    "care_plan": CARE_PLAN_PRICING["pricing"]["care_plan"],
                }
            },
        )
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        # $667/yr on a $100 cap — allowed, because the cap is on one-time work.
        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(
                care_plan=UpsellCarePlanSelection(tier_key="gold", fixture_count=24)
            ),
            user_id=1,
            role=LEAD,
        )
        assert quote.total == 0
        assert quote.proposal_document["care_plan"]["selected"] == "gold"


async def test_menu_reports_the_limit_to_the_capped_seller_only() -> None:
    """So the UI can warn before the lead builds something they can't send."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=LIMIT_PRICING)
        await _catalog_item(db, ws, name="Uplighting", price=640.0)

        service = UpsellService(db)
        assert (await service.list_attachable_catalog(ws.id, role=LEAD)).proposal_limit == 500
        assert (await service.list_attachable_catalog(ws.id, role=ADMIN)).proposal_limit is None


# --------------------------------------------------------------------------- #
# Care Plans — recurring revenue, which is a subscription and not a line item
# --------------------------------------------------------------------------- #
async def test_care_plan_tiers_are_priced_by_fixture_count() -> None:
    """``base + per_fixture × (count - free)``, priced by the shared engine."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=CARE_PLAN_PRICING)

        priced = await UpsellService(db).list_care_plans(ws.id, fixture_count=18)
        assert priced.configured
        by_key = {option.key: option for option in priced.options}
        # 18 fixtures, 10 free → 8 chargeable.
        assert by_key["essential"].price == 179 + 15 * 8
        assert by_key["gold"].price == 359 + 22 * 8
        assert by_key["gold"].visits == 4


async def test_fixture_count_at_or_below_the_free_allowance_is_base_price() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=CARE_PLAN_PRICING)

        priced = await UpsellService(db).list_care_plans(ws.id, fixture_count=6)
        assert {option.key: option.price for option in priced.options} == {
            "essential": 179,
            "gold": 359,
        }


async def test_workspace_without_tiers_reports_unconfigured_rather_than_erroring() -> None:
    """Not selling maintenance is a normal state, not a failure."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)

        priced = await UpsellService(db).list_care_plans(ws.id, fixture_count=12)
        assert priced.configured is False
        assert priced.options == []


async def test_care_plan_is_not_billed_as_a_one_time_line_item() -> None:
    """The plan is a subscription; the quote total stays the hardware sold.

    Folding an annual plan price into ``line_items`` would bill a recurring
    subscription once on the install invoice *and* still provision the recurring
    visits on approval — charging the customer twice for different things.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=CARE_PLAN_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(
                care_plan=UpsellCarePlanSelection(tier_key="gold", fixture_count=18)
            ),
            user_id=1,
            role=LEAD,
        )

        assert quote.line_items == []
        assert quote.total == 0
        assert quote.proposal_document is not None
        assert quote.proposal_document["care_plan"]["selected"] == "gold"


async def test_selling_a_care_plan_provisions_recurring_visits_on_approval() -> None:
    """The end-to-end proof that a technician's sale becomes real recurring work.

    Without the ``proposal_document`` snapshot this whole path is a no-op: the
    customer would pay, and nothing would ever schedule a maintenance visit or
    record that they are on Gold.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=CARE_PLAN_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        created = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(
                care_plan=UpsellCarePlanSelection(tier_key="gold", fixture_count=18)
            ),
            user_id=1,
            role=LEAD,
        )

        quote = await db.get(Quote, created.id)
        assert quote is not None
        plans = await ServicePlanProvisioner(db).provision_from_quote(quote)

        assert len(plans) == 1
        plan = plans[0]
        assert plan.plan_type == ServicePlanType.LIGHTING_CARE_PLAN
        assert plan.care_plan_tier == "gold"
        assert plan.title == "Care Plan — Gold"
        # 4 visits a year → a visit every three months.
        assert plan.interval == 3


async def test_care_plan_and_hardware_sell_together_on_one_proposal() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=CARE_PLAN_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Uplighting", price=640.0)

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(
                line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=1)],
                care_plan=UpsellCarePlanSelection(tier_key="essential", fixture_count=12),
            ),
            user_id=1,
            role=LEAD,
        )

        # The $640 configured hardware price is authoritative; care is recurring.
        assert quote.total == 640.0
        assert quote.proposal_document["care_plan"]["selected"] == "essential"


async def test_care_plan_snapshot_freezes_every_priced_option() -> None:
    """The provisioner reads ``visits``/``name`` off the frozen option.

    Freezing the whole list also means a later pricing-config edit cannot change
    what this customer already bought.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=CARE_PLAN_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(
                care_plan=UpsellCarePlanSelection(tier_key="gold", fixture_count=18)
            ),
            user_id=1,
            role=LEAD,
        )

        document = quote.proposal_document["care_plan"]
        assert document["fixture_count"] == 18
        assert document["free_fixtures"] == 10
        assert {option["key"] for option in document["options"]} == {"essential", "gold"}
        gold = next(o for o in document["options"] if o["key"] == "gold")
        assert gold["visits"] == 4
        assert gold["price"] == 359 + 22 * 8


async def test_unknown_care_plan_tier_is_refused_without_leaving_a_draft() -> None:
    """An operator can retire a tier mid-shift; a stale phone must not orphan a quote."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=CARE_PLAN_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        with pytest.raises(UpsellCarePlanUnavailableError):
            await UpsellService(db).create_quote(
                ws.id,
                job.id,
                UpsellQuoteRequest(
                    care_plan=UpsellCarePlanSelection(tier_key="platinum", fixture_count=12)
                ),
                user_id=1,
                role=LEAD,
            )

        remaining = (
            (await db.execute(select(Quote).where(Quote.workspace_id == ws.id))).scalars().all()
        )
        assert remaining == []


async def test_care_plan_on_a_workspace_without_tiers_is_refused() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        with pytest.raises(UpsellCarePlanUnavailableError):
            await UpsellService(db).create_quote(
                ws.id,
                job.id,
                UpsellQuoteRequest(
                    care_plan=UpsellCarePlanSelection(tier_key="gold", fixture_count=12)
                ),
                user_id=1,
                role=LEAD,
            )


async def test_care_plan_only_proposal_is_titled_for_what_it_sells() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=CARE_PLAN_PRICING)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(
                care_plan=UpsellCarePlanSelection(tier_key="gold", fixture_count=12)
            ),
            user_id=1,
            role=LEAD,
        )
        assert quote.title == "Care plan for Pressure wash"


async def test_care_plan_on_someone_elses_job_is_refused() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, settings=CARE_PLAN_PRICING)
        contact = await _contact(db, ws)
        await _technician(db, ws, user_id=1)
        other = await _technician(db, ws, user_id=2)
        their_job = await _job(db, ws, contact)
        await _assign(db, their_job, other)

        with pytest.raises(JobNotFoundError):
            await UpsellService(db).create_quote(
                ws.id,
                their_job.id,
                UpsellQuoteRequest(
                    care_plan=UpsellCarePlanSelection(tier_key="gold", fixture_count=12)
                ),
                user_id=1,
                role=LEAD,
            )


# --------------------------------------------------------------------------- #
# Delivery — a valid job id must not unlock an unrelated quote
# --------------------------------------------------------------------------- #
async def test_delivery_refuses_a_quote_for_a_different_customer() -> None:
    """The hole this check exists to close.

    The technician is legitimately assigned to ``my_job``. Without the
    quote-to-contact binding they could pass their own job id alongside any other
    quote id in the workspace and deliver someone else's proposal.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        mine, stranger = await _contact(db, ws, "Mine"), await _contact(db, ws, "Stranger")
        tech = await _technician(db, ws, user_id=1)
        my_job = await _job(db, ws, mine)
        await _assign(db, my_job, tech)

        stranger_quote = Quote(
            workspace_id=ws.id,
            contact_id=stranger.id,
            number=f"QUO-{uuid.uuid4().hex[:6]}",
            title="Not yours",
        )
        db.add(stranger_quote)
        await db.flush()

        with pytest.raises(UpsellQuoteNotForJobError):
            await UpsellService(db).deliver_quote(
                ws.id, my_job.id, stranger_quote.id, channel="sms", user_id=1, role=LEAD
            )
