"""Real-DB integration tests for the sales-wizard quote flow.

Covers the full loop the React wizard drives: a workspace with a pricing config
+ fixture catalog → ``preview_from_wizard`` (live document) →
``save_from_wizard`` (draft quote + snapshot + recomputed line items) →
``send`` → the public proposal read carries the snapshot. Marked
``integration`` (Postgres: JSONB settings/columns, quote numbering, enums).
Run with ``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine
from app.models.catalog import CatalogItem
from app.models.contact import Contact
from app.models.lighting_project import LightingProject
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.pricing import MAINTENANCE_THROUGH_TOKEN
from app.schemas.proposal_wizard import (
    ProposalMockup,
    ProposalWizardPayload,
    WizardBistroRun,
    WizardBistroSelection,
    WizardCategoryCount,
    WizardCharge,
    WizardChristmasSelection,
    WizardClient,
    WizardDepositSelection,
    WizardFixtureQty,
    WizardPermanentSelection,
)
from app.schemas.quote import QuoteUpdate
from app.services.exceptions import ConflictError
from app.services.quotes import QuoteService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


# Minimal two-tier lighting config: 11% finance buffer + 3% cash reserve,
# commission out of margin — the exact defaults the uploaded wizard shipped.
PRICING = {
    "financing": {
        "enabled": True,
        "provider": "Wisetack",
        "max_amount": 25000,
        "terms": [6, 12, 24],
        "default_term": 24,
        "apr": 0.0,
        "fee_buffer": 0.11,
    },
    "cash_discount": {"enabled": True, "card_reserve_rate": 0.03},
    "commission": {"enabled": True, "rate": 0.12, "in_price": False},
    "tier_order": ["best", "good"],
    "tiers": [
        {
            "key": "best",
            "label": "Best — The Premier",
            "name": "The Premier",
            "sections": [
                {"title": "Transformer", "item_ids": ["tx-luxor"]},
                {"title": "Fixtures", "item_ids": ["up-zdc"]},
            ],
        },
        {
            "key": "good",
            "label": "Good — The Starter",
            "name": "The Starter",
            "sections": [
                {"title": "Transformer", "item_ids": ["tx-ex"]},
                {"title": "Fixtures", "item_ids": ["up-evo"]},
            ],
        },
    ],
    "care_plan": {
        "free_fixtures": 10,
        "tiers": [
            {
                "key": "premier",
                "name": "Premier",
                "base": 299,
                "per_fixture": 25,
                "visits": 2,
                "repair_discount": 0.10,
                "popular": True,
            }
        ],
    },
    "savings": {
        "per_visit_value": 179,
        "avoided_repair_per_fixture": 28,
        "assumed_repair_spend_per_fixture": 40,
    },
    "bistro": {
        "enabled": True,
        "minimum": 2307,
        "temporary": {
            "label": "Temporary Bistro Lighting",
            "lights_per_ft": 10,
            "poles_per_ft": 400,
            "lights_inventory_sku": "BISTRO-TEMP-200FT",
            "poles_inventory_sku": "BISTRO-TEMP-POLE",
            "stock_feet_per_light_unit": 200,
        },
        "permanent": {
            "label": "Permanent Bistro Lighting",
            "lights_per_ft": 20,
            "poles_per_ft": 350,
            "lights_inventory_sku": "BISTRO-PERM-FT",
            "poles_inventory_sku": "BISTRO-PERM-POLE",
            "stock_feet_per_light_unit": 1,
        },
        "tiers": [{"key": "medium", "name": "Medium", "per_ft": 18.11, "classic_per_ft": 15.50}],
        "color": {
            "name": "Color Changing Bistro Lights",
            "hardware": 577,
            "strand_lengths": [50, 40, 20, 10, 4, 2],
        },
        "classic": {
            "name": "Classic Bistro Lights",
            "hardware": 35,
            "min_footage": 200,
            "bulb_spacing_ft": 2,
        },
    },
    "permanent": {
        "enabled": True,
        "per_ft": 30,
        "controller_base": 300,
        "per_channel": 50,
        "included_channels": 2,
    },
    "christmas": {
        "enabled": True,
        "roofline_per_ft": 6,
        "tree_rates": [{"key": "medium", "name": "Medium tree", "price": 260}],
        "bush_rates": [{"key": "small", "name": "Small bush", "price": 35}],
        "wreath_rates": [{"key": "standard", "name": "Wreath", "price": 85}],
        "takedown_rate": 0.25,
        "storage_price": 200,
    },
}

FIXTURES = [
    # (sku, name, net price, transformer, components)
    (
        "tx-luxor",
        "Luxor Smart 300W Transformer",
        2266,
        True,
        [{"sku": "59409312", "description": "Luxor 300W Transformer", "qty": 1}],
    ),
    (
        "up-zdc",
        "ZDC Color Uplight",
        785,
        False,
        [{"sku": "59400232", "description": "NP ZDC FB Up Light Black", "qty": 1}],
    ),
    ("tx-ex", "EX 150W Transformer", 504, True, []),
    ("up-evo", "EVO Accent Uplight", 172, False, []),
]


async def _make_lighting_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Lighting Co",
        slug=f"light-{uuid.uuid4().hex[:8]}",
        settings={"pricing": PRICING},
    )
    db.add(ws)
    await db.flush()
    for sku, name, price, transformer, components in FIXTURES:
        db.add(
            CatalogItem(
                workspace_id=ws.id,
                name=name,
                sku=sku,
                kind="product",
                unit_price=price,
                attributes={"transformer": True} if transformer else None,
                components=components or None,
            )
        )
    await db.flush()
    return ws


def _payload() -> ProposalWizardPayload:
    return ProposalWizardPayload(
        client=WizardClient(first_name="Sarah", last_name="Henderson", rep_name="Max"),
        quantities=[
            WizardFixtureQty(item_id="tx-luxor", quantity=1),
            WizardFixtureQty(item_id="up-zdc", quantity=12),
            WizardFixtureQty(item_id="tx-ex", quantity=1),
            WizardFixtureQty(item_id="up-evo", quantity=8),
        ],
        additional_charges=[WizardCharge(description="Core drilling", net_amount=500)],
        bistro=WizardBistroSelection(product="color", tier="medium", feet=120),
    )


async def test_preview_computes_document_from_config_and_catalog() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        doc = await svc.preview_from_wizard(ws.id, _payload())

        assert doc.tier_order == ["best", "good"]
        assert doc.headline_tier == "best"  # highest base wins

        best = doc.tiers[0]
        # Net 2266 grossed by the 11% buffer: round(2266 / 0.89) = 2546.
        assert best.lines[0].unit_price == 2546.0
        # Zero-qty rows still ship (the calculator shows every fixture's price).
        good = doc.tiers[1]
        assert {line.item_id for line in good.lines} == {"tx-ex", "up-evo"}

        # base = 2546 + 12×882 = 13130; additional = round(500/0.89) = 562.
        assert best.pricing.base == 13130.0
        assert best.pricing.additional == 562.0
        assert best.pricing.financed_total == 13692.0
        # Cash backs out the buffer, keeps the 3% reserve: 13692×0.89×1.03.
        assert best.pricing.cash_total == 12551.0
        assert best.pricing.monthly_by_term[24] == 570.5

        # Care Plan counts non-transformer fixtures of the headline tier.
        assert doc.care_plan is not None
        assert doc.care_plan.fixture_count == 12
        premier = doc.care_plan.options[0]
        assert premier.price == 349.0  # 299 + 25 × (12 − 10)

        # Bistro: 120 ft fills as 50+50+20 strands; grossed rate + hardware.
        assert doc.bistro is not None
        assert doc.bistro.ordered_ft == 120.0
        assert doc.bistro.total == 3090.0
        assert doc.bistro.min_applied is False


def test_bistro_run_rejects_negative_pole_counts() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        WizardBistroRun(installation="permanent", feet=100, pole_count=-1)


async def test_bistro_only_design_creates_a_clear_customer_quote() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        payload = _payload()
        payload.quantities = []
        payload.additional_charges = []
        payload.categories = ["landscape", "bistro"]
        payload.bistro = WizardBistroSelection(
            runs=[WizardBistroRun(installation="permanent", feet=312.5, pole_count=2)]
        )
        svc = QuoteService(db)

        doc = await svc.preview_from_wizard(ws.id, payload)
        assert doc.bistro is not None
        assert doc.bistro.lights_cost == 7022
        assert doc.bistro.poles_cost == 787
        assert doc.bistro.total == 7809
        assert doc.grand_financed_total == 7809

        quote = await svc.save_from_wizard(ws.id, payload)
        assert float(quote.total) == 7809
        assert len(quote.line_items) == 1
        assert quote.line_items[0].name == "Bistro Lighting"
        assert quote.line_items[0].description == ("312.5 ft Permanent Bistro Lighting · 2 poles")


async def _assert_bistro_allocations_created(
    db: AsyncSession,
    service: QuoteService,
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.models.inventory import InventoryItem, InventoryJobAllocation

    await service.approve_quote(workspace_id, quote_id)
    start = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
    converted = await service.convert_quote(
        workspace_id,
        quote_id,
        create_invoice=False,
        scheduled_start=start,
        scheduled_end=start + timedelta(hours=3),
        confirm_unpaid_deposit=True,
    )
    allocation_rows = (
        await db.execute(
            select(InventoryJobAllocation, InventoryItem)
            .join(InventoryItem, InventoryItem.id == InventoryJobAllocation.item_id)
            .where(
                InventoryJobAllocation.workspace_id == workspace_id,
                InventoryJobAllocation.job_id == converted.job_id,
            )
        )
    ).all()
    planned_by_sku = {item.sku: allocation for allocation, item in allocation_rows}
    assert planned_by_sku["BISTRO-TEMP-200FT"].planned_quantity == 1
    assert planned_by_sku["BISTRO-TEMP-200FT"].behavior == "reusable"
    assert planned_by_sku["BISTRO-PERM-FT"].planned_quantity == 50


async def test_grouped_bistro_runs_price_and_persist_without_legacy_labels() -> None:
    from app.models.inventory import InventoryItem
    from app.schemas.inventory import ReceiveStockRequest
    from app.services.inventory import StockService

    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        for sku, name, unit, quantity in (
            ("BISTRO-PERM-FT", "Permanent Bistro footage", "ft", 200),
            ("BISTRO-PERM-POLE", "Permanent Bistro pole", "each", 10),
            ("BISTRO-TEMP-200FT", "Temporary Bistro set", "set", 3),
            ("BISTRO-TEMP-POLE", "Temporary Bistro pole", "each", 10),
        ):
            item = InventoryItem(workspace_id=ws.id, sku=sku, name=name, unit_of_measure=unit)
            db.add(item)
            await db.flush()
            await StockService(db).receive(
                ws.id, item.id, ReceiveStockRequest(quantity=quantity, unit_cost=1)
            )
        payload = _payload()
        payload.client.email = "bistro-reservation@example.com"
        payload.client.phone = "+15551235555"
        payload.bistro = WizardBistroSelection(
            runs=[
                WizardBistroRun(installation="temporary", feet=100, pole_count=2),
                WizardBistroRun(installation="permanent", feet=50, pole_count=3),
                WizardBistroRun(installation="temporary", feet=25, pole_count=1),
            ]
        )

        svc = QuoteService(db)
        doc = await svc.preview_from_wizard(ws.id, payload)

        assert doc.bistro is not None
        assert doc.bistro.pricing_mode == "installation"
        assert doc.bistro.feet == 175
        assert [row.feet for row in doc.bistro.installations] == [125, 50]
        assert doc.bistro.lights_cost == 2528
        assert doc.bistro.poles_cost == 2528
        assert doc.bistro.total == 5056

        quote = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        bistro_line = next(line for line in quote.line_items if line.name == "Bistro Lighting")
        assert bistro_line.description == (
            "125 ft Temporary Bistro Lighting · 3 poles · 50 ft Permanent Bistro Lighting · 3 poles"
        )
        assert float(bistro_line.unit_price) == 5056

        parts = {part.sku: part for part in doc.fulfillment}
        assert parts["59409312"].qty == 1.0
        assert parts["59400232"].qty == 12.0
        assert parts["BISTRO-TEMP-200FT"].qty == 1.0
        assert parts["BISTRO-TEMP-200FT"].inventory_behavior == "reusable"
        assert parts["BISTRO-TEMP-POLE"].qty == 3.0
        assert parts["BISTRO-PERM-FT"].qty == 50.0
        assert parts["BISTRO-PERM-FT"].inventory_behavior == "consumable"
        assert parts["BISTRO-PERM-POLE"].qty == 3.0

        assert doc.inventory_availability is not None
        assert doc.inventory_availability.has_requirements is True
        assert doc.inventory_availability.untracked_items == 2
        assert quote.proposal_document is not None
        snapshot = quote.proposal_document["inventory_availability"]
        assert snapshot["untracked_items"] == 2

        await _assert_bistro_allocations_created(db, svc, ws.id, uuid.UUID(str(quote.id)))


async def test_price_book_mode_skips_finance_and_uses_catalog_prices_exactly() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        payload = _payload()
        payload.pricing_source = "price_book"
        payload.categories = ["landscape"]
        payload.bistro = None

        doc = await svc.preview_from_wizard(ws.id, payload)

        best = doc.tiers[0]
        assert doc.pricing_source == "price_book"
        assert best.lines[0].unit_price == 2266.0
        assert best.lines[1].unit_price == 785.0
        assert best.pricing.base == 11686.0
        assert best.pricing.additional == 500.0
        assert best.pricing.financed_total == 12186.0
        assert best.pricing.cash_total == 12186.0
        assert best.pricing.monthly_payment == 0
        assert best.pricing.monthly_by_term == {}
        assert doc.financing is not None
        assert doc.financing.enabled is False
        assert doc.financing.terms == []
        assert doc.selected_cash_total == doc.selected_financed_total == 12186.0
        assert doc.grand_monthly_payment == 0

        quote = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        assert quote.total == 12186.0
        assert quote.proposal_document is not None
        assert quote.proposal_document["pricing_source"] == "price_book"


async def test_save_persists_snapshot_and_recomputed_lines() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        quote = await svc.save_from_wizard(ws.id, _payload(), created_by_id=None)

        assert quote.status == "draft"
        assert quote.title == "The Henderson Residence — Lighting Proposal"
        # Headline-tier fixtures (qty > 0) + the charge + the bistro line.
        names = [line.name for line in quote.line_items]
        assert names == [
            "Luxor Smart 300W Transformer",
            "ZDC Color Uplight",
            "Core drilling",
            "Color Changing Bistro Lights",
        ]
        # Quote total = financed tier total + bistro total (server-computed).
        assert quote.total == 13692.0 + 3090.0
        assert quote.proposal_document is not None
        assert quote.proposal_document["selected_tier"] == "best"
        assert quote.proposal_document["selected_cash_total"] == 12551.0


async def test_public_read_carries_the_snapshot() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        saved = await svc.save_from_wizard(ws.id, _payload(), created_by_id=None)
        sent = await svc.mark_sent(ws.id, uuid.UUID(str(saved.id)))
        assert sent.public_token

        public = await svc.get_public_proposal(sent.public_token)
        assert public.proposal_document is not None
        assert public.proposal_document["headline_tier"] == "best"
        tiers = public.proposal_document["tiers"]
        assert [t["key"] for t in tiers] == ["best", "good"]
        # The public page leads with cash/check; both figures ride the snapshot.
        assert tiers[0]["pricing"]["cash_total"] == 12551.0
        assert tiers[0]["pricing"]["financed_total"] == 13692.0


async def test_mockups_persist_into_snapshot_and_public_read() -> None:
    """Rep-uploaded design mockups ride the payload into the saved snapshot and
    survive onto the public proposal read (the client-facing gallery source)."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        payload = _payload()
        payload.mockups = [
            ProposalMockup(image="data:image/jpeg;base64,AAAA", caption="Front elevation"),
            ProposalMockup(image="data:image/jpeg;base64,BBBB", caption=None),
        ]

        # Live preview echoes the mockups back for the rep presentation screen.
        doc = await svc.preview_from_wizard(ws.id, payload)
        assert [m.image for m in doc.mockups] == [
            "data:image/jpeg;base64,AAAA",
            "data:image/jpeg;base64,BBBB",
        ]
        assert doc.mockups[0].caption == "Front elevation"

        # Saved snapshot + public read carry the same gallery for the client link.
        saved = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        sent = await svc.mark_sent(ws.id, uuid.UUID(str(saved.id)))
        public = await svc.get_public_proposal(sent.public_token)
        mockups = public.proposal_document["mockups"]
        assert [m["image"] for m in mockups] == [
            "data:image/jpeg;base64,AAAA",
            "data:image/jpeg;base64,BBBB",
        ]
        assert mockups[0]["caption"] == "Front elevation"


async def test_wizard_defaults_selected_tier_to_headline_and_respects_pick() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        payload = _payload()
        payload.selected_tier = "good"
        doc = await svc.preview_from_wizard(ws.id, payload)
        assert doc.headline_tier == "best"
        assert doc.selected_tier == "good"
        # Selected figures follow the pick, not the headline.
        good = doc.tiers[1]
        assert doc.selected_financed_total == good.pricing.financed_total

        payload.selected_tier = "nope"
        doc2 = await svc.preview_from_wizard(ws.id, payload)
        assert doc2.selected_tier == "best"  # unknown pick falls back to headline


async def test_deliver_quote_emails_snapshot_client(monkeypatch) -> None:
    """deliver(email) sends to the wizard snapshot's client email (no Contact
    row needed) and transitions the quote to sent."""
    sent_calls: list[dict] = []

    async def fake_send_quote_email(**kwargs):  # noqa: ANN003
        sent_calls.append(kwargs)
        return True

    from app.services import email as email_module

    monkeypatch.setattr(email_module, "send_quote_email", fake_send_quote_email)

    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        payload = _payload()
        payload.client.email = "sarah@example.com"
        saved = await svc.save_from_wizard(ws.id, payload, created_by_id=None)

        result = await svc.deliver_quote(ws.id, uuid.UUID(str(saved.id)), channel="email", to=None)

        assert result.ok is True
        assert result.to == "sarah@example.com"
        assert sent_calls and sent_calls[0]["to_email"] == "sarah@example.com"
        assert "/p/quotes/" in (sent_calls[0]["proposal_url"] or "")

        refreshed = await svc.get_quote(ws.id, uuid.UUID(str(saved.id)))
        assert refreshed.status == "sent"
        assert refreshed.public_token


async def test_deliver_quote_reports_a_failed_email_instead_of_ok(monkeypatch) -> None:
    """A send Resend never accepted must not come back as a delivered quote.

    ``send_quote_email`` returns False on failure rather than raising, so an
    ignored return value produced the worst possible outcome: the operator sees
    "emailed", the customer's inbox stays empty, and nobody finds out until the
    follow-up call. The quote must still be ``sent`` with a live link, because
    the token is already minted and copying that link is the operator's retry.
    """
    from app.services.exceptions import ValidationError

    async def failing_send(**kwargs):  # noqa: ANN003
        return False

    from app.services import email as email_module

    monkeypatch.setattr(email_module, "send_quote_email", failing_send)

    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        payload = _payload()
        payload.client.email = "sarah@example.com"
        saved = await svc.save_from_wizard(ws.id, payload, created_by_id=None)

        with pytest.raises(ValidationError, match="Couldn't send that email"):
            await svc.deliver_quote(ws.id, uuid.UUID(str(saved.id)), channel="email", to=None)

        refreshed = await svc.get_quote(ws.id, uuid.UUID(str(saved.id)))
        assert refreshed.status == "sent"
        assert refreshed.public_token


async def test_explicit_quote_resend_uses_a_fresh_provider_key(monkeypatch) -> None:
    """Every deliberate delivery must create a new email.

    Resend returns the original message when an idempotency key is replayed. The
    quote dialog labels later clicks as "Re-send email", so reusing the
    revision-key there reports success without putting a replacement link in
    the customer's inbox.
    """
    keys: list[str] = []

    async def capture(**kwargs):  # noqa: ANN003
        keys.append(str(kwargs["idempotency_key"]))
        return True

    from app.services import email as email_module

    monkeypatch.setattr(email_module, "send_quote_email", capture)

    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        payload = _payload()
        payload.client.email = "sarah@example.com"
        saved = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        qid = uuid.UUID(str(saved.id))

        await svc.deliver_quote(ws.id, qid, channel="email", to=None)
        await svc.deliver_quote(ws.id, qid, channel="email", to=None)

        assert len(keys) == 2
        assert keys[0] != keys[1], "an explicit re-send must create a new email"


async def test_mark_sent_survives_a_failed_courtesy_email(monkeypatch) -> None:
    """``mark_sent`` is a status change, not a delivery promise.

    An operator using it has usually sent the quote by their own means and is
    recording that fact; the courtesy email riding along must never undo the
    transition. This is the deliberate asymmetry with ``deliver_quote`` above.
    """

    async def failing_send(**kwargs):  # noqa: ANN003
        return False

    from app.services import email as email_module

    monkeypatch.setattr(email_module, "send_quote_email", failing_send)

    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        payload = _payload()
        payload.client.email = "sarah@example.com"
        saved = await svc.save_from_wizard(ws.id, payload, created_by_id=None)

        result = await svc.mark_sent(ws.id, uuid.UUID(str(saved.id)))

        assert result.status == "sent"
        assert result.public_token


async def test_combined_multi_category_quote_prices_and_saves_all_lines() -> None:
    """A quote mixing landscape + permanent + christmas prices every line and the
    saved quote total equals the document's server-derived grand total."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        payload = ProposalWizardPayload(
            client=WizardClient(first_name="Sam", last_name="Rivera", rep_name="Max"),
            categories=["landscape", "permanent", "christmas"],
            quantities=[
                WizardFixtureQty(item_id="tx-luxor", quantity=1),
                WizardFixtureQty(item_id="up-zdc", quantity=10),
            ],
            permanent=WizardPermanentSelection(feet=100, channels=5),
            christmas=WizardChristmasSelection(
                roofline_feet=150,
                items={
                    "trees": [WizardCategoryCount(key="medium", quantity=2)],
                    "bushes": [WizardCategoryCount(key="small", quantity=4)],
                    "wreaths": [WizardCategoryCount(key="standard", quantity=2)],
                },
                takedown=True,
                storage=False,
            ),
        )

        doc = await svc.preview_from_wizard(ws.id, payload)
        assert doc.categories == ["landscape", "permanent", "christmas"]
        assert [s.key for s in doc.category_sections] == ["permanent", "christmas"]
        perm = doc.category_sections[0]
        chris = doc.category_sections[1]
        # The 100 ft kit costs 1,249; standard 3× markup = 3,747 net -> 4,210 financed.
        # Deprecated controller/channel inputs are intentionally ignored by kit pricing.
        assert perm.financed_total == 4210.0
        # roofline 900->1011; trees 2*260=520->584; bushes 140->157; wreaths 170->191;
        # takedown 0.25*1730=432.5->486.
        assert chris.financed_total == 2429.0
        # Grand total = landscape selected tier + both category sections.
        assert doc.grand_financed_total == doc.selected_financed_total + 4210.0 + 2429.0

        # The rep wizard is single-service, but the API stays permissive: a payload
        # spanning service paths still prices and is recorded as "mixed".
        assert doc.service == "mixed"

        quote = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        names = [line.name for line in quote.line_items]
        assert "Permanent Holiday Lighting" in names
        assert "Christmas Lighting" in names
        # Server-recomputed quote total matches the document's grand total exactly.
        assert quote.total == doc.grand_financed_total
        assert quote.proposal_document["categories"] == [
            "landscape",
            "permanent",
            "christmas",
        ]
        assert quote.proposal_document["service"] == "mixed"


async def test_christmas_only_quote_has_no_landscape_tiers() -> None:
    """A single-category Christmas quote prices without any landscape tier cards."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        payload = ProposalWizardPayload(
            client=WizardClient(first_name="Dana", last_name="Cole"),
            categories=["christmas"],
            christmas=WizardChristmasSelection(
                roofline_feet=200,
                items={"trees": [WizardCategoryCount(key="medium", quantity=1)]},
            ),
        )
        doc = await svc.preview_from_wizard(ws.id, payload)
        assert doc.tiers == []
        assert doc.care_plan is None
        assert doc.selected_financed_total == 0
        assert [s.key for s in doc.category_sections] == ["christmas"]
        assert doc.grand_financed_total == doc.category_sections[0].financed_total
        # Christmas is its own service path, branched apart from every other line.
        assert doc.service == "christmas"

        quote = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        assert [line.name for line in quote.line_items] == ["Christmas Lighting"]
        assert quote.total == doc.grand_financed_total
        assert quote.proposal_document["service"] == "christmas"


async def test_christmas_section_carries_dated_value_props() -> None:
    """The seasonal section ships its selling points with the maintenance cutoff
    already rendered, so the customer reads a real date and not a placeholder."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        payload = ProposalWizardPayload(
            client=WizardClient(first_name="Dana", last_name="Cole"),
            categories=["christmas"],
            christmas=WizardChristmasSelection(roofline_feet=200),
        )
        doc = await svc.preview_from_wizard(ws.id, payload)
        props = doc.category_sections[0].value_props

        assert props, "a christmas section must sell, not just itemize"
        bodies = [p.body for p in props]
        # The token is an internal detail; a customer must never see one.
        assert not any(MAINTENANCE_THROUGH_TOKEN in body for body in bodies)
        assert any("December 23" in body for body in bodies)
        # The three promises the operator sells this season on.
        joined = " ".join(bodies).lower()
        assert "maintenance is included" in joined
        assert "we own the bulbs" in joined
        assert "off-season storage" in joined


async def test_value_props_follow_the_configured_maintenance_date() -> None:
    """Moving the cutoff in Settings moves the promise, with no code change."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        settings = dict(ws.settings or {})
        pricing = dict(settings["pricing"])
        pricing["christmas"] = {
            **pricing["christmas"],
            "maintenance_through_month": 12,
            "maintenance_through_day": 20,
        }
        settings["pricing"] = pricing
        ws.settings = settings
        await db.commit()

        svc = QuoteService(db)
        doc = await svc.preview_from_wizard(
            ws.id,
            ProposalWizardPayload(
                client=WizardClient(first_name="Dana", last_name="Cole"),
                categories=["christmas"],
                christmas=WizardChristmasSelection(roofline_feet=200),
            ),
        )
        bodies = " ".join(p.body for p in doc.category_sections[0].value_props)
        assert "December 20" in bodies
        assert "December 23" not in bodies


async def test_permanent_section_has_no_seasonal_value_props() -> None:
    """Seasonal promises (takedown, storage, nothing permanent on the home) are
    false for the permanent LED product, so they must not leak onto it."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        doc = await svc.preview_from_wizard(
            ws.id,
            ProposalWizardPayload(
                client=WizardClient(first_name="Dana", last_name="Cole"),
                categories=["permanent"],
                permanent=WizardPermanentSelection(feet=100, channels=3),
            ),
        )
        assert doc.category_sections[0].key == "permanent"
        assert doc.category_sections[0].value_props == []


async def test_permanent_only_quote_is_its_own_service_path() -> None:
    """Permanent LED track is a separate service from seasonal Christmas, so a
    permanent-only quote is never labeled (or presented as) Christmas."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        payload = ProposalWizardPayload(
            client=WizardClient(first_name="Nia", last_name="Brooks"),
            categories=["permanent"],
            permanent=WizardPermanentSelection(feet=120, channels=4),
        )
        doc = await svc.preview_from_wizard(ws.id, payload)

        assert doc.service == "permanent"
        assert [s.key for s in doc.category_sections] == ["permanent"]
        assert doc.tiers == []


async def test_landscape_service_covers_bistro_without_becoming_mixed() -> None:
    """Bistro belongs to the landscape service path, so landscape + bistro is one
    service (not a cross-service mix)."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)

        payload = ProposalWizardPayload(
            client=WizardClient(first_name="Ada", last_name="Lin"),
            categories=["landscape", "bistro"],
            quantities=[WizardFixtureQty(item_id="up-zdc", quantity=6)],
            bistro=WizardBistroSelection(product="color", tier="easy", feet=60),
        )
        doc = await svc.preview_from_wizard(ws.id, payload)

        assert doc.service == "landscape"
        assert doc.bistro is not None

        quote = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        assert quote.proposal_document["service"] == "landscape"
        assert quote.total == doc.grand_financed_total


async def test_deliver_quote_validates_missing_destination_and_channel() -> None:
    from app.services.exceptions import ValidationError

    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        saved = await svc.save_from_wizard(ws.id, _payload(), created_by_id=None)
        qid = uuid.UUID(str(saved.id))

        with pytest.raises(ValidationError, match="No client email"):
            await svc.deliver_quote(ws.id, qid, channel="email", to=None)
        with pytest.raises(ValidationError, match="No client phone"):
            await svc.deliver_quote(ws.id, qid, channel="sms", to=None)
        with pytest.raises(ValidationError, match="Unknown delivery channel"):
            await svc.deliver_quote(ws.id, qid, channel="fax", to=None)


async def test_wizard_deposit_persists_and_shows_in_document() -> None:
    """A rep-set wizard deposit is priced into the document and quote."""

    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        payload = _payload()
        payload.deposit = WizardDepositSelection(mode="percentage", value=50)

        doc = await svc.preview_from_wizard(ws.id, payload)
        # Deposit is taken on the combined financed total (13692 + 3090 = 16782).
        assert doc.grand_financed_total == 16782.0
        assert doc.deposit_mode == "percentage"
        assert doc.deposit_amount == 8391.0

        saved = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        assert saved.deposit_percentage == 50.0
        assert saved.deposit_amount == 8391.0
        assert saved.deposit_required is True
        assert saved.deposit_paid is False


async def test_landscape_wizard_snapshots_visual_workspace_deposit_and_link() -> None:  # noqa: PLR0915
    from datetime import UTC, datetime, timedelta

    from app.models.field_service import Job

    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        ws.settings = {
            **ws.settings,
            "pricing": {
                **ws.settings["pricing"],
                "deposit": {"enabled": True, "mode": "percentage", "value": 25},
            },
        }
        contact = Contact(
            workspace_id=ws.id,
            first_name="Sarah",
            phone_number="+15551234567",
            phone_hash="wizard-link-test",
        )
        db.add(contact)
        await db.flush()
        document = {
            "version": 2,
            "activeShotId": "install-front",
            "shots": [
                {
                    "id": "install-front",
                    "photo": {
                        "dataUrl": "data:image/png;base64,AAAA",
                        "width": 1200,
                        "height": 800,
                    },
                    "design": {"calibration": None, "runs": [], "items": [], "planImages": []},
                    "dusk": 0.35,
                }
            ],
            "updatedAt": "2026-08-12T00:00:00Z",
        }
        project = LightingProject(
            workspace_id=ws.id,
            contact_id=contact.id,
            name="Front elevation",
            document=document,
            version=1,
            installation_shot_id="install-front",
        )
        db.add(project)
        await db.flush()

        payload = _payload()
        payload.contact_id = contact.id
        payload.categories = ["landscape"]
        payload.bistro = None
        payload.notes = "Install path lights along the front walk."
        payload.lighting_project_id = project.id
        preview = await svc.preview_from_wizard(ws.id, payload)
        assert preview.deposit_value == 25
        assert preview.deposit_amount == round(preview.grand_financed_total * 0.25, 2)
        assert preview.mockups[0].image == "data:image/png;base64,AAAA"
        assert preview.mockups[0].caption == "Front elevation lighting design"

        saved = await svc.save_from_wizard(ws.id, payload, created_by_id=None)

        assert saved.lighting_project_id == project.id
        assert saved.deposit_percentage == 25
        assert saved.deposit_required is True
        assert saved.proposal_document is not None
        assert saved.proposal_document["mockups"][0]["image"] == "data:image/png;base64,AAAA"
        assert project.opportunity_id is None

        await svc.approve_quote(ws.id, uuid.UUID(str(saved.id)))
        scheduled_start = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
        converted = await svc.convert_quote(
            ws.id,
            uuid.UUID(str(saved.id)),
            create_invoice=False,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_start + timedelta(hours=3),
            confirm_unpaid_deposit=True,
        )
        job = await db.get(Job, converted.job_id)
        assert job is not None
        assert job.title == saved.title
        assert job.description == payload.notes
        assert job.lighting_project_id == project.id
        assert job.scheduled_start == scheduled_start
        assert converted.quote.opportunity_id is not None
        no_deposit_payload = _payload()
        no_deposit_payload.contact_id = contact.id
        no_deposit_payload.categories = ["landscape"]
        no_deposit_payload.bistro = None
        no_deposit_payload.lighting_project_id = project.id
        no_deposit_payload.deposit = None
        ws.settings = {
            **ws.settings,
            "pricing": {
                **ws.settings["pricing"],
                "deposit": {"enabled": False, "mode": "percentage", "value": 0},
            },
        }
        no_deposit = await QuoteService(db).save_from_wizard(
            ws.id, no_deposit_payload, created_by_id=None
        )
        assert no_deposit.deposit_amount is None
        assert no_deposit.deposit_required is False


async def test_wizard_links_contact_and_converts_to_scheduled_job() -> None:
    """A wizard quote with client phone details resolves/creates a contact so an
    approved quote can convert into a job (which needs a contact)."""
    from datetime import UTC, datetime, timedelta

    from app.models.field_service import Job

    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        payload = _payload()
        payload.client.email = "newlead@example.com"
        payload.client.phone = "+15551230000"

        saved = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        assert saved.contact_id is not None  # contact was created + linked

        qid = uuid.UUID(str(saved.id))
        await svc.approve_quote(ws.id, qid)
        start = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
        result = await svc.convert_quote(
            ws.id,
            qid,
            create_invoice=False,
            scheduled_start=start,
            scheduled_end=start + timedelta(hours=3),
        )
        assert result.job_id is not None
        job = await db.get(Job, result.job_id)
        assert job is not None
        assert job.status == "scheduled"

        # Re-quoting the same phone reuses the contact rather than duplicating it.
        again = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        assert again.contact_id == saved.contact_id


# --------------------------------------------------------------------------- #
# The client picks their own package on the public page, then pays for it.
# --------------------------------------------------------------------------- #
async def _sent_wizard_quote(
    svc: QuoteService,
    workspace_id: uuid.UUID,
    *,
    deposit: WizardDepositSelection | None = None,
) -> str:
    """Save + send a two-package wizard proposal, returning its share token."""
    payload = _payload()
    payload.deposit = deposit
    saved = await svc.save_from_wizard(workspace_id, payload, created_by_id=None)
    sent = await svc.mark_sent(workspace_id, uuid.UUID(str(saved.id)))
    assert sent.public_token
    return sent.public_token


async def test_public_read_offers_every_package_with_its_own_deposit() -> None:
    """The client page can only ask "which package?" if the server prices each
    one — total *and* money due today, so no figure is computed in a browser."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        token = await _sent_wizard_quote(
            svc, ws.id, deposit=WizardDepositSelection(mode="percentage", value=50)
        )

        public = await svc.get_public_proposal(token)
        packages = {p.key: p for p in public.packages}
        assert set(packages) == {"best", "good"}

        # Each package total is its tier plus the charges/bistro that ride along
        # with every package — the same recipe the quote's line items use.
        assert packages["best"].total == 13692.0 + 3090.0
        assert packages["best"].is_selected is True
        assert packages["good"].is_selected is False
        assert packages["good"].total < packages["best"].total

        # Deposit is priced per package, not once off the rep's pick.
        assert packages["best"].deposit_amount == round(packages["best"].total * 0.5, 2)
        assert packages["good"].deposit_amount == round(packages["good"].total * 0.5, 2)


async def test_client_package_choice_repoints_quote_lines_totals_and_deposit() -> None:
    """Choosing the cheaper package on approve must move the money with it:
    line items, quote total, snapshot, and the deposit Stripe will charge."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        token = await _sent_wizard_quote(
            svc, ws.id, deposit=WizardDepositSelection(mode="percentage", value=50)
        )

        before = await svc.get_public_proposal(token)
        good = next(p for p in before.packages if p.key == "good")

        result = await svc.approve_public(
            token, proposal_version=before.proposal_version, selected_tier="good"
        )
        assert result.status == "approved"
        assert result.deposit_required is True
        assert result.deposit_amount == good.deposit_amount

        after = await svc.get_public_proposal(token)
        assert after.total == good.total
        assert after.proposal_document["selected_tier"] == "good"
        # Lines describe the chosen package's fixtures, not the rep's.
        names = [li.name for li in after.line_items]
        assert names == [
            "EX 150W Transformer",
            "EVO Accent Uplight",
            "Core drilling",
            "Color Changing Bistro Lights",
        ]
        assert after.deposit_amount == good.deposit_amount


async def test_client_cannot_invent_a_package() -> None:
    """Only a real, priced package on this proposal is sellable — anything else
    is rejected rather than silently approving at the rep's price."""
    from app.services.exceptions import ValidationError

    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        token = await _sent_wizard_quote(svc, ws.id)

        with pytest.raises(ValidationError):
            await svc.approve_public(token, proposal_version=1, selected_tier="platinum")

        # The proposal is untouched and still acceptable.
        public = await svc.get_public_proposal(token)
        assert public.status == "sent"
        assert public.proposal_document["selected_tier"] == "best"


async def test_package_switch_is_refused_after_the_quote_is_decided() -> None:
    """An approved quote is a signed agreement; a late package switch must not
    rewrite what was already accepted."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        token = await _sent_wizard_quote(svc, ws.id)

        await svc.approve_public(token, proposal_version=1, selected_tier="good")
        approved = await svc.get_public_proposal(token)
        assert approved.proposal_document["selected_tier"] == "good"

        # Re-approving with a different package is idempotent, not a rewrite.
        await svc.approve_public(token, proposal_version=1, selected_tier="best")
        again = await svc.get_public_proposal(token)
        assert again.proposal_document["selected_tier"] == "good"
        assert again.total == approved.total


async def test_single_package_proposal_offers_no_choice() -> None:
    """One priced package is not a choice — the page shouldn't stage one."""
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        payload = _payload()
        # Drop the "good" tier's quantities so only "best" carries a price.
        payload.quantities = [
            WizardFixtureQty(item_id="tx-luxor", quantity=1),
            WizardFixtureQty(item_id="up-zdc", quantity=12),
        ]
        saved = await svc.save_from_wizard(ws.id, payload, created_by_id=None)
        sent = await svc.mark_sent(ws.id, uuid.UUID(str(saved.id)))

        public = await svc.get_public_proposal(sent.public_token)
        assert public.packages == []


async def test_wizard_update_reprices_sent_quote_in_place_and_preserves_link() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        saved = await svc.save_from_wizard(ws.id, _payload(), created_by_id=None)
        sent = await svc.mark_sent(ws.id, uuid.UUID(str(saved.id)))
        token = sent.public_token
        original_total = sent.total

        changed = _payload()
        changed.title = "Updated lighting plan"
        changed.quantities[1].quantity = 20
        changed.deposit = WizardDepositSelection(mode="fixed", value=875)
        updated = await svc.update_from_wizard(ws.id, uuid.UUID(str(sent.id)), changed)

        assert updated.id == sent.id
        assert updated.number == sent.number
        assert updated.status == "sent"
        assert updated.public_token == token
        assert updated.total > original_total
        assert updated.proposal_version == sent.proposal_version + 1
        assert updated.proposal_input is not None
        assert updated.proposal_input.title == "Updated lighting plan"
        assert updated.proposal_input.quantities[1].quantity == 20
        assert updated.proposal_input.deposit is not None
        assert updated.proposal_input.deposit.value == 875

        public = await svc.get_public_proposal(token)
        assert public.proposal_version == updated.proposal_version
        assert public.total == updated.total


@pytest.mark.parametrize("source_status", ["approved", "declined", "expired"])
async def test_decided_wizard_quotes_fork_with_auditable_lineage(
    source_status: str,
) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        saved = await svc.save_from_wizard(ws.id, _payload(), created_by_id=None)
        source = await db.get(Quote, uuid.UUID(str(saved.id)))
        assert source is not None
        source.status = source_status
        await db.commit()
        original_document = source.proposal_document
        original_total = source.total

        changed = _payload()
        changed.quantities[1].quantity = 18
        revision = await svc.revise_from_wizard(ws.id, source.id, changed, created_by_id=None)
        await db.refresh(source)

        assert source.status == source_status
        assert source.total == original_total
        assert source.proposal_document == original_document
        assert revision.id != source.id
        assert revision.status == "draft"
        assert revision.public_token is None
        assert revision.revision_of_quote_id == source.id
        assert revision.revision_root_quote_id == source.id
        assert revision.revision_number == 2
        assert revision.proposal_input is not None
        assert revision.proposal_input.quantities[1].quantity == 18


async def test_payment_touched_quote_cannot_change_and_revision_copies_no_payment() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        saved = await svc.save_from_wizard(ws.id, _payload(), created_by_id=None)
        sent = await svc.mark_sent(ws.id, uuid.UUID(str(saved.id)))
        source = await db.get(Quote, uuid.UUID(str(sent.id)))
        assert source is not None
        source.deposit_checkout_session_id = "cs_locked_terms"
        await db.commit()

        with pytest.raises(ConflictError) as exc_info:
            await svc.update_from_wizard(ws.id, source.id, _payload())
        assert exc_info.value.code == "quote_revision_required"

        changed = _payload()
        changed.quantities[1].quantity = 16
        revision = await svc.revise_from_wizard(ws.id, source.id, changed, created_by_id=None)

        assert source.deposit_checkout_session_id == "cs_locked_terms"
        assert revision.status == "draft"
        assert revision.deposit_paid_at is None
        persisted = await db.get(Quote, uuid.UUID(str(revision.id)))
        assert persisted is not None
        assert persisted.deposit_checkout_session_id is None
        assert persisted.deposit_payment_intent_id is None


async def test_basic_edit_syncs_deposit_input_then_payment_locks_further_edits() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        saved = await svc.save_from_wizard(ws.id, _payload(), created_by_id=None)

        edited = await svc.update_quote(
            ws.id,
            uuid.UUID(str(saved.id)),
            QuoteUpdate(title="Pool courtyard", deposit_amount_fixed=625),
        )
        assert edited.proposal_input is not None
        assert edited.proposal_input.title == "Pool courtyard"
        assert edited.proposal_input.deposit is not None
        assert edited.proposal_input.deposit.mode == "fixed"
        assert edited.proposal_input.deposit.value == 625

        source = await db.get(Quote, uuid.UUID(str(saved.id)))
        assert source is not None
        source.deposit_payment_intent_id = "pi_locked_terms"
        await db.commit()
        with pytest.raises(ConflictError):
            await svc.update_quote(
                ws.id, source.id, QuoteUpdate(title="Must not overwrite paid terms")
            )


async def test_public_approval_rejects_the_version_rendered_before_an_edit() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        token = await _sent_wizard_quote(svc, ws.id)
        rendered = await svc.get_public_proposal(token)

        changed = _payload()
        changed.quantities[1].quantity = 19
        source_result = await db.execute(select(Quote).where(Quote.public_token == token))
        source = source_result.scalar_one()
        await svc.update_from_wizard(ws.id, source.id, changed)

        with pytest.raises(ConflictError) as exc_info:
            await svc.approve_public(token, proposal_version=rendered.proposal_version)
        assert exc_info.value.code == "proposal_changed"
        with pytest.raises(ConflictError) as legacy_info:
            await svc.approve_public(token, proposal_version=None)
        assert legacy_info.value.code == "proposal_version_required"

        current = await svc.get_public_proposal(token)
        assert current.status == "sent"
        approved = await svc.approve_public(token, proposal_version=current.proposal_version)
        assert approved.status == "approved"


async def test_untouched_version_one_proposal_accepts_old_frontend_payload() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_lighting_workspace(db)
        svc = QuoteService(db)
        token = await _sent_wizard_quote(svc, ws.id)

        approved = await svc.approve_public(token, proposal_version=None)

        assert approved.status == "approved"


async def test_conversion_marker_requires_revision_even_if_status_looks_open() -> None:
    quote = Quote(
        workspace_id=uuid.uuid4(),
        number="Q-TEST",
        status="sent",
        converted_job_id=uuid.uuid4(),
    )
    assert QuoteService._wizard_quote_requires_revision(quote) is True
