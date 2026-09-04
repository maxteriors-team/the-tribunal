"""Routing + error-mapping tests for the public client-proposal endpoints.

Verifies the ``/p/quotes`` router is wired with ``ServiceErrorRoute`` so a
service ``NotFoundError`` maps to 404, and that a resolved proposal serializes
to a safe payload (no internal ids). DB-free via a get_db override + a
monkeypatched service.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.api.v1 import quotes as quotes_module
from app.schemas.proposal import (
    PublicProposal,
    PublicProposalActionResult,
    PublicProposalBranding,
    PublicProposalLineItem,
)
from app.services.exceptions import NotFoundError


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _app() -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(quotes_module.public_router, prefix="/api/v1/p/quotes")
    return app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver")


async def test_unknown_token_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _raise(self: object, token: str) -> PublicProposal:
        raise NotFoundError("Proposal not found")

    monkeypatch.setattr(quotes_module.QuoteService, "get_public_proposal", _raise)
    async with await _client() as ac:
        resp = await ac.get("/api/v1/p/quotes/nope")
    assert resp.status_code == 404


async def test_sent_proposal_returns_safe_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    proposal = PublicProposal(
        token="tok",
        number="QUO-000001",
        title="Backyard lighting",
        status="sent",
        proposal_version=1,
        currency="USD",
        subtotal=720.0,
        tax_amount=0.0,
        discount_amount=0.0,
        total=720.0,
        line_items=[
            PublicProposalLineItem(
                name="Fixtures", quantity=6, unit_price=120.0, discount=0.0, total=720.0
            )
        ],
        branding=PublicProposalBranding(business_name="Maxteriors Lighting"),
    )

    async def _ok(self: object, token: str) -> PublicProposal:
        return proposal

    monkeypatch.setattr(quotes_module.QuoteService, "get_public_proposal", _ok)
    async with await _client() as ac:
        resp = await ac.get("/api/v1/p/quotes/tok")

    assert resp.status_code == 200
    body = resp.json()
    assert body["number"] == "QUO-000001"
    assert body["branding"]["business_name"] == "Maxteriors Lighting"
    assert len(body["line_items"]) == 1
    # No internal identifiers leak into the client payload.
    for leaked in ("id", "workspace_id", "contact_id", "converted_invoice_id"):
        assert leaked not in body


async def test_approve_requires_and_forwards_rendered_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str | int | None] = {}

    async def _approve(
        self: object,
        token: str,
        *,
        proposal_version: int,
        selected_tier: str | None = None,
        payment_option: str | None = None,
    ) -> PublicProposalActionResult:
        seen["token"] = token
        seen["proposal_version"] = proposal_version
        seen["selected_tier"] = selected_tier
        seen["payment_option"] = payment_option
        return PublicProposalActionResult(token="tok", status="approved", message="Thank you!")

    monkeypatch.setattr(quotes_module.QuoteService, "approve_public", _approve)
    async with await _client() as ac:
        missing = await ac.post("/api/v1/p/quotes/tok/approve")
        resp = await ac.post("/api/v1/p/quotes/tok/approve", json={"proposal_version": 7})

    assert missing.status_code == 422
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert seen == {
        "token": "tok",
        "proposal_version": 7,
        "selected_tier": None,
        "payment_option": None,
    }


async def test_approve_forwards_the_clients_package_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The package key the client picked must reach the service — it's what
    re-derives the totals and the deposit they're about to be charged."""
    seen: dict[str, str | int | None] = {}

    async def _approve(
        self: object,
        token: str,
        *,
        proposal_version: int,
        selected_tier: str | None = None,
        payment_option: str | None = None,
    ) -> PublicProposalActionResult:
        seen["proposal_version"] = proposal_version
        seen["selected_tier"] = selected_tier
        seen["payment_option"] = payment_option
        return PublicProposalActionResult(
            token="tok",
            status="approved",
            message="Thank you!",
            deposit_required=True,
            deposit_amount=1055.0,
        )

    monkeypatch.setattr(quotes_module.QuoteService, "approve_public", _approve)
    async with await _client() as ac:
        resp = await ac.post(
            "/api/v1/p/quotes/tok/approve",
            json={
                "proposal_version": 4,
                "selected_tier": "good",
                "payment_option": "financing",
            },
        )

    assert resp.status_code == 200
    assert seen == {
        "proposal_version": 4,
        "selected_tier": "good",
        "payment_option": "financing",
    }
    assert resp.json()["deposit_amount"] == 1055.0


async def test_approve_rejects_customer_supplied_financial_terms() -> None:
    async with await _client() as ac:
        response = await ac.post(
            "/api/v1/p/quotes/tok/approve",
            json={
                "proposal_version": 1,
                "payment_option": "financing",
                "total": 1,
                "apr": 0,
                "merchant_fee_rate": 0,
            },
        )

    assert response.status_code == 422
