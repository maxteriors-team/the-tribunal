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
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine
from app.models.catalog import CatalogItem
from app.models.workspace import Workspace
from app.schemas.proposal_wizard import (
    ProposalWizardPayload,
    WizardBistroSelection,
    WizardCharge,
    WizardClient,
    WizardFixtureQty,
)
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

        # Internal fulfillment aggregates SKU components for the selected tier.
        skus = {part.sku: part.qty for part in doc.fulfillment}
        assert skus["59409312"] == 1.0
        assert skus["59400232"] == 12.0


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
