"""Adding a service to a quote that already exists.

The operator-facing idea is one thing ("they also want the gutters done"), but a
quote stores its money in one of two places depending on how it was built, and
only one of them survives on any given quote:

* **wizard quote** — ``proposal_document`` is the truth and the line items are
  *derived* from it. A line item written directly is invisible on the client
  proposal (which renders the document) and is deleted outright the next time the
  quote reprices.
* **plain quote** — line items are the truth; it may still carry preview-only media.

``QuoteService.add_service`` hides that split. These tests exist to hold the
consequences of it, because every one of them fails *silently* in production:
the rep sees the service on the internal quote either way, and only the customer
sees it missing.

Real-DB (JSONB snapshot, quote numbering, enums), so marked ``integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.exceptions import HTTPException

from app.db.session import AsyncSessionLocal, engine
from app.models.catalog import CatalogItem
from app.schemas.proposal_wizard import ProposalDocument, ProposalMockup
from app.schemas.quote import QuoteCreate, QuoteLineItemCreate, QuoteServiceCreate
from app.services.exceptions import ConflictError, NotFoundError
from app.services.quotes import QuoteService

from .test_wizard_flow import (  # reuse the configured lighting workspace + payload
    _make_lighting_workspace,
    _payload,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _wizard_quote(svc: QuoteService, workspace_id: uuid.UUID):
    """A saved two-package wizard quote."""
    return await svc.save_from_wizard(workspace_id, _payload(), created_by_id=None)


async def _plain_quote(
    svc: QuoteService,
    workspace_id: uuid.UUID,
    *,
    base_catalog_item_id: uuid.UUID | None = None,
):
    """A saved quote with no snapshot — line items are its only price."""
    return await svc.create_quote(
        workspace_id,
        QuoteCreate(
            title="Driveway wash",
            line_items=[
                QuoteLineItemCreate(
                    name="Pressure washing",
                    unit_price=400.0,
                    catalog_item_id=base_catalog_item_id,
                )
            ],
        ),
        created_by_id=None,
    )


# --------------------------------------------------------------------------- #
# Wizard quotes: the service has to reach the customer, and stay there.
# --------------------------------------------------------------------------- #
async def test_added_service_reaches_the_client_proposal_and_every_package_price() -> None:
    """The whole point of the feature.

    A wizard quote's client page renders the document, and its package cards are
    priced from it — so a service that only ever became a line item would be
    invisible to the customer while looking fine to the rep. Assert it lands on
    the document *and* moves every package total, not just the quote's.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        quote = await _wizard_quote(svc, ws.id)
        quote_id = uuid.UUID(str(quote.id))

        sent = await svc.mark_sent(ws.id, quote_id)
        assert sent.public_token
        before = await svc.get_public_proposal(sent.public_token)
        prices_before = {p.key: p.total for p in before.packages}

        await svc.add_service(
            ws.id, quote_id, QuoteServiceCreate(name="Gutter cleaning", amount=600.0)
        )

        after = await svc.get_public_proposal(sent.public_token)
        # On the document the client actually reads.
        assert "Gutter cleaning" in [
            c["description"] for c in after.proposal_document["additional_charges"]
        ]
        # And on the price of every package they can choose between.
        prices_after = {p.key: p.total for p in after.packages}
        assert set(prices_after) == set(prices_before)
        for key, price in prices_after.items():
            assert price > prices_before[key], f"package {key} did not reprice"


async def test_added_service_survives_the_client_switching_packages() -> None:
    """The regression that makes a raw line item wrong.

    Picking a different package rebuilds every line from the document. A service
    stored as a line item vanishes at that moment — after the customer has
    already been shown it and agreed to it.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        quote = await _wizard_quote(svc, ws.id)
        quote_id = uuid.UUID(str(quote.id))
        sent = await svc.mark_sent(ws.id, quote_id)
        assert sent.public_token

        updated = await svc.add_service(
            ws.id, quote_id, QuoteServiceCreate(name="Gutter cleaning", amount=600.0)
        )

        await svc.approve_public(
            sent.public_token,
            proposal_version=updated.proposal_version,
            selected_tier="good",
        )

        after = await svc.get_public_proposal(sent.public_token)
        assert "Gutter cleaning" in [li.name for li in after.line_items]
        assert "Gutter cleaning" in [
            c["description"] for c in after.proposal_document["additional_charges"]
        ]


async def test_wizard_service_is_grossed_up_like_the_builder_does() -> None:
    """A service added after saving must price identically to the same service
    typed during the build — otherwise *when* the rep added it changes the
    customer's price. The config carries an 11% finance buffer."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        quote = await _wizard_quote(svc, ws.id)

        detail = await svc.add_service(
            ws.id,
            uuid.UUID(str(quote.id)),
            QuoteServiceCreate(name="Gutter cleaning", amount=600.0),
        )

        added = next(s for s in detail.services if s.name == "Gutter cleaning")
        # Same gross-up the wizard applies to its own add-on row: net / (1 - .11).
        assert added.amount == pytest.approx(600.0 / 0.89, rel=1e-3)
        assert added.amount > 600.0


async def test_removing_a_wizard_service_reprices_back_down() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        quote = await _wizard_quote(svc, ws.id)
        quote_id = uuid.UUID(str(quote.id))
        original_total = float(quote.total)

        added = await svc.add_service(
            ws.id, quote_id, QuoteServiceCreate(name="Gutter cleaning", amount=600.0)
        )
        service_id = next(s.id for s in added.services if s.name == "Gutter cleaning")
        assert float(added.total) > original_total

        removed = await svc.remove_service(ws.id, quote_id, service_id)
        assert "Gutter cleaning" not in [s.name for s in removed.services]
        assert float(removed.total) == pytest.approx(original_total)


async def test_services_omit_fixture_lines_the_rep_cannot_edit_here() -> None:
    """A wizard quote's fixtures are priced by the design and can only change by
    rebuilding it. Listing them as removable services would offer an edit the
    server refuses, so only the add-on charges are services."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        quote = await _wizard_quote(svc, ws.id)

        detail = await svc.get_quote(ws.id, uuid.UUID(str(quote.id)))
        line_names = {li.name for li in detail.line_items}
        service_names = {s.name for s in detail.services}

        assert "ZDC Color Uplight" in line_names  # a fixture line exists
        assert "ZDC Color Uplight" not in service_names  # but is not a service
        assert service_names == {"Core drilling"}  # the payload's own add-on


# --------------------------------------------------------------------------- #
# Plain quotes: the same operation, the other persistence.
# --------------------------------------------------------------------------- #
async def test_preview_media_does_not_turn_a_plain_quote_into_a_wizard_quote() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                title="Permanent lighting",
                line_items=[QuoteLineItemCreate(name="Permanent lighting", unit_price=400.0)],
            ),
            created_by_id=None,
            proposal_document=ProposalDocument(
                service="permanent",
                mockups=[
                    ProposalMockup(
                        image="data:image/jpeg;base64,/9j/2Q==",
                        caption="Proposed roofline",
                    )
                ],
            ),
        )
        quote_id = uuid.UUID(str(quote.id))

        detail = await svc.get_quote(ws.id, quote_id)
        assert detail.is_wizard_quote is False
        assert [service.name for service in detail.services] == ["Permanent lighting"]

        updated = await svc.add_service(
            ws.id, quote_id, QuoteServiceCreate(name="Gutter cleaning", amount=600.0)
        )
        assert {line.name for line in updated.line_items} == {
            "Permanent lighting",
            "Gutter cleaning",
        }
        assert float(updated.total) == pytest.approx(1000.0)

        sent = await svc.mark_sent(ws.id, quote_id)
        assert sent.public_token is not None
        public = await svc.get_public_proposal(sent.public_token)
        assert public.proposal_document is not None
        assert public.proposal_document["mockups"][0]["caption"] == "Proposed roofline"


async def test_plain_quote_service_becomes_a_line_item() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        quote = await _plain_quote(svc, ws.id)
        quote_id = uuid.UUID(str(quote.id))

        detail = await svc.add_service(
            ws.id, quote_id, QuoteServiceCreate(name="Gutter cleaning", amount=600.0)
        )

        assert "Gutter cleaning" in [li.name for li in detail.line_items]
        # No document, so no gross-up: the amount is the price as typed.
        added = next(s for s in detail.services if s.name == "Gutter cleaning")
        assert added.amount == pytest.approx(600.0)
        assert float(detail.total) == pytest.approx(1000.0)

        removed = await svc.remove_service(ws.id, quote_id, added.id)
        assert "Gutter cleaning" not in [li.name for li in removed.line_items]
        assert float(removed.total) == pytest.approx(400.0)


async def test_service_from_the_price_book_snapshots_its_category_as_an_attach() -> None:
    """Picking from the price book is what makes the add count as an attach
    rather than an uncategorized custom charge, on both quote shapes."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        washing = CatalogItem(
            workspace_id=ws.id,
            name="Pressure washing",
            kind="service",
            unit_price=400.0,
            service_category="washing",
        )
        gutters = CatalogItem(
            workspace_id=ws.id,
            name="Gutter cleaning",
            kind="service",
            unit_price=600.0,
            service_category="gutters",
        )
        db.add_all([washing, gutters])
        await db.flush()
        svc = QuoteService(db)
        # The base job needs a category of its own, or the added service simply
        # becomes the quote's primary service instead of an attachment to it.
        quote = await _plain_quote(svc, ws.id, base_catalog_item_id=washing.id)

        detail = await svc.add_service(
            ws.id,
            uuid.UUID(str(quote.id)),
            QuoteServiceCreate(name=gutters.name, amount=600.0, catalog_item_id=gutters.id),
        )

        line = next(li for li in detail.line_items if li.name == "Gutter cleaning")
        assert line.service_category == "gutters"
        # The quote now reads as two categorized services rather than one job
        # plus an untracked custom charge, which is what puts the add into
        # attach-rate reporting. Primary is the biggest category by value, so
        # the $600 gutters lead and the $400 wash is the attachment.
        assert detail.primary_service == "gutters"
        assert detail.attach_count == 1


async def test_a_foreign_workspaces_catalog_item_cannot_categorize_a_service() -> None:
    """``catalog_item_id`` is resolved inside the workspace, so an id from
    another tenant leaves the line uncategorized instead of leaking a category."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        other = await _make_lighting_workspace(db)
        foreign = CatalogItem(
            workspace_id=other.id,
            name="Gutter cleaning",
            kind="service",
            unit_price=600.0,
            service_category="gutters",
        )
        db.add(foreign)
        await db.flush()
        svc = QuoteService(db)
        quote = await _plain_quote(svc, ws.id)

        detail = await svc.add_service(
            ws.id,
            uuid.UUID(str(quote.id)),
            QuoteServiceCreate(name="Gutter cleaning", amount=600.0, catalog_item_id=foreign.id),
        )

        line = next(li for li in detail.line_items if li.name == "Gutter cleaning")
        assert line.service_category is None


# --------------------------------------------------------------------------- #
# Guard rails
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("wizard", [True, False])
async def test_a_decided_quote_refuses_new_services(wizard: bool) -> None:
    """An approved quote is a signed agreement. Adding work to it after the fact
    would change what the customer already accepted."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        quote = await (_wizard_quote if wizard else _plain_quote)(svc, ws.id)
        quote_id = uuid.UUID(str(quote.id))
        await svc.approve_quote(ws.id, quote_id)

        with pytest.raises(ConflictError):
            await svc.add_service(
                ws.id, quote_id, QuoteServiceCreate(name="Gutter cleaning", amount=600.0)
            )


@pytest.mark.parametrize("wizard", [True, False])
async def test_removing_an_unknown_service_is_a_404_not_a_silent_no_op(wizard: bool) -> None:
    """A delete that reports success without deleting anything is how a rep ends
    up sending a quote they believe they corrected."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        quote = await (_wizard_quote if wizard else _plain_quote)(svc, ws.id)

        with pytest.raises(NotFoundError):
            await svc.remove_service(ws.id, uuid.UUID(str(quote.id)), uuid.uuid4().hex)


async def test_a_service_cannot_be_added_to_another_workspaces_quote() -> None:
    """Tenant scoping is enforced by the same ``get_or_404`` every other quote
    mutation goes through, so a foreign quote is indistinguishable from one that
    does not exist."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        other = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        quote = await _plain_quote(svc, ws.id)

        with pytest.raises(HTTPException) as caught:
            await svc.add_service(
                other.id,
                uuid.UUID(str(quote.id)),
                QuoteServiceCreate(name="Gutter cleaning", amount=600.0),
            )
        assert caught.value.status_code == 404
