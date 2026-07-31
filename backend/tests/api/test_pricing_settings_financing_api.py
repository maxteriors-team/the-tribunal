"""Contract tests for editing the financing block of the pricing settings.

Financing presentation is now service-category aware: a workspace lists which
services offer a monthly-payment estimate and the project subtotal that
qualifies. Settings → Pricing writes that through ``PUT .../pricing``, so this
covers the operator round-trip the ``FinancingSettingsCard`` depends on —
category keys normalize the way the card assumes, a financing edit does not
clobber a sibling block, the disclaimer can never be emptied away, and the
margin knobs survive the block-replace write.

DB-free via dependency overrides + a stateful fake workspace whose ``settings``
dict persists across requests (same shape as the proposal-template contract
tests).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import settings as settings_module
from app.schemas.pricing import DEFAULT_FINANCING_DISCLAIMER, PricingSettings
from app.services.quotes.proposal_pricing import financing_estimate

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _auth_app(workspace: SimpleNamespace) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    async def override_get_workspace() -> SimpleNamespace:
        return workspace

    async def override_get_current_user() -> SimpleNamespace:
        return SimpleNamespace(id=1, is_active=True, email="op@example.com")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.include_router(settings_module.router, prefix="/api/v1")
    return app


@pytest.fixture
def workspace() -> SimpleNamespace:
    # A real dict for ``settings`` so the merge logic actually mutates + persists
    # across requests (refresh is a no-op under the mocked db).
    return SimpleNamespace(id=WS_ID, name="Maxteriors", is_active=True, settings={})


@pytest.fixture
async def auth_client(workspace: SimpleNamespace) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_auth_app(workspace)),
        base_url="http://testserver",
    ) as ac:
        yield ac


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/pricing"


def _financing(**overrides) -> dict:
    """A full financing block, the way the settings card PUTs it."""
    block = {
        "enabled": True,
        "provider": "Wisetack",
        "max_amount": 25000,
        "terms": [6, 12, 24],
        "default_term": 24,
        "apr": 0.0,
        "fee_buffer": 0.11,
        "category_minimums": {"landscape": 0, "roofing": 1000},
        "disclaimer": "Estimates only.",
    }
    block.update(overrides)
    return block


async def test_defaults_finance_lighting_and_floor_core_services(
    auth_client: AsyncClient,
) -> None:
    """An unconfigured workspace already offers financing beyond lighting."""
    body = (await auth_client.get(_url())).json()
    minimums = body["financing"]["category_minimums"]

    assert minimums["landscape"] == 0
    assert minimums["christmas"] == 0
    # Core exterior work is financed, but only above a meaningful subtotal.
    assert minimums["roofing"] == 1000
    assert minimums["siding"] == 1000
    assert minimums["gutters"] == 1000


async def test_put_then_get_round_trips_category_minimums(
    auth_client: AsyncClient,
) -> None:
    resp = await auth_client.put(
        _url(),
        json={
            "financing": _financing(
                category_minimums={"roofing": 1500, "siding": 2500},
            )
        },
    )
    assert resp.status_code == 200

    body = (await auth_client.get(_url())).json()
    assert body["financing"]["category_minimums"] == {"roofing": 1500, "siding": 2500}


async def test_category_keys_normalize_case_and_whitespace(
    auth_client: AsyncClient,
) -> None:
    """The card trims + lowercases before saving; the server must agree.

    Categories come from free-form price-book strings, so " Roofing " and
    "roofing" have to be one entry or a workspace ends up with a duplicate that
    never matches a quote.
    """
    await auth_client.put(
        _url(),
        json={"financing": _financing(category_minimums={"  Roofing ": 1500})},
    )

    body = (await auth_client.get(_url())).json()
    assert body["financing"]["category_minimums"] == {"roofing": 1500}


async def test_editing_financing_does_not_clobber_other_pricing_blocks(
    auth_client: AsyncClient,
) -> None:
    await auth_client.put(_url(), json={"tax": {"enabled": True, "rate": 0.07}})
    await auth_client.put(_url(), json={"financing": _financing()})

    body = (await auth_client.get(_url())).json()
    assert body["tax"]["enabled"] is True
    assert body["tax"]["rate"] == 0.07
    assert body["financing"]["category_minimums"] == {"landscape": 0, "roofing": 1000}


async def test_blank_disclaimer_falls_back_to_the_standard_one(
    auth_client: AsyncClient,
) -> None:
    """A payment figure can never be presented without a disclaimer.

    The card saves an emptied field as ``null``; the read must hand back copy the
    proposal surfaces can render, not nothing.
    """
    await auth_client.put(_url(), json={"financing": _financing(disclaimer=None)})

    body = (await auth_client.get(_url())).json()
    assert body["financing"]["disclaimer"] is None

    # …and the estimate the client is shown carries the standard wording.
    config = PricingSettings(**{"financing": _financing(disclaimer=None)})
    estimate = financing_estimate(9000, {"roofing": 9000}, config)
    assert estimate is not None
    assert estimate.disclaimer == DEFAULT_FINANCING_DISCLAIMER


async def test_margin_knobs_survive_a_financing_edit(auth_client: AsyncClient) -> None:
    """``fee_buffer`` rides through the block-replace write untouched.

    The block PUT replaces the whole ``financing`` object, so an editor that
    forgets a field would silently reset the gross-up rate and destroy margin on
    every financed job.
    """
    await auth_client.put(_url(), json={"financing": _financing(fee_buffer=0.09)})

    body = (await auth_client.get(_url())).json()
    assert body["financing"]["fee_buffer"] == 0.09
    assert body["financing"]["max_amount"] == 25000
    assert body["financing"]["terms"] == [6, 12, 24]


async def test_negative_minimum_rejected_at_the_edge(auth_client: AsyncClient) -> None:
    resp = await auth_client.put(
        _url(),
        json={"financing": _financing(category_minimums={"roofing": -1})},
    )
    assert resp.status_code == 422
