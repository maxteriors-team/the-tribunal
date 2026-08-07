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

import pytest

from app.db.session import AsyncSessionLocal, engine
from app.models.catalog import CatalogItem
from app.models.contact import Contact
from app.models.field_service import Crew, Job, JobAssignment, JobStatus, Technician
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.upsell import UpsellQuoteLine, UpsellQuoteRequest
from app.services.field_service.exceptions import JobNotFoundError
from app.services.upsell import UpsellService
from app.services.upsell.exceptions import (
    UpsellItemNotAttachableError,
    UpsellNoLineItemsError,
    UpsellQuoteNotForJobError,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

FIELD = "technician"
ADMIN = "admin"


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the asyncpg pool around each test to avoid closed-loop reuse."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Lights", slug=f"lights-{uuid.uuid4().hex[:8]}")
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

        listed = await UpsellService(db).list_jobs(ws.id, 1, FIELD)
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

        listed = await UpsellService(db).list_jobs(ws.id, 1, FIELD)
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
            await UpsellService(db).job_customer(ws.id, their_job.id, 1, FIELD)


async def test_login_without_a_technician_record_owns_nothing() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        job = await _job(db, ws, contact)

        service = UpsellService(db)
        # Listing is a normal empty state, not an error…
        assert (await service.list_jobs(ws.id, 999, FIELD)).total == 0
        # …but reaching for a specific job still fails closed.
        with pytest.raises(JobNotFoundError):
            await service.job_customer(ws.id, job.id, 999, FIELD)


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

        customer = await UpsellService(db).job_customer(ws.id, job.id, 1, FIELD)
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
            attributes={"per_linear_foot": "yes please", "minimum": "two thousand"},
        )

        listed = await UpsellService(db).list_attachable_catalog(ws.id)
        assert listed.items[0].price_unit is None


# --------------------------------------------------------------------------- #
# Quote creation — server-side pricing
# --------------------------------------------------------------------------- #
async def test_quote_prices_come_from_the_catalog_not_the_request() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws)
        tech = await _technician(db, ws, user_id=1)
        job = await _job(db, ws, contact)
        await _assign(db, job, tech)
        item = await _catalog_item(db, ws, name="Landscape lighting", price=2400.0)

        quote = await UpsellService(db).create_quote(
            ws.id,
            job.id,
            UpsellQuoteRequest(line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=2)]),
            user_id=1,
            role=FIELD,
        )
        assert len(quote.line_items) == 1
        line = quote.line_items[0]
        assert line.name == "Landscape lighting"
        assert line.unit_price == 2400.0
        assert line.total == 4800.0
        # Attributed to the technician so attach-rate reporting can pay the spiff.
        assert quote.contact_id == contact.id


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
                role=FIELD,
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
                role=FIELD,
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
                role=FIELD,
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
                ws.id, job.id, UpsellQuoteRequest(line_items=[]), user_id=1, role=FIELD
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
                ws.id, my_job.id, stranger_quote.id, channel="sms", user_id=1, role=FIELD
            )
