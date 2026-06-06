"""API tests for the Deal Coach endpoints on the opportunities router.

Two layers:
* **Auth**: every coach route requires authentication.
* **Happy-path**: ``get_db`` / ``get_workspace`` / ``get_current_user`` are
  overridden and ``DealCoachService`` is patched so the handlers are driven
  end-to-end with deterministic fixtures (no DB, no OpenAI).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import opportunities as opportunities_module
from app.schemas.deal_coach import (
    AtRiskDeal,
    AtRiskDealsResponse,
    DealCoachCard,
    DealSignals,
    DraftedAction,
    NextBestAction,
)

WS_ID = uuid.uuid4()
OPP_ID = uuid.uuid4()
ACTION_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_card() -> DealCoachCard:
    return DealCoachCard(
        opportunity_id=OPP_ID,
        workspace_id=WS_ID,
        name="Acme Expansion",
        amount=12000.0,
        currency="USD",
        primary_contact_id=42,
        contact_name="Jane Doe",
        deal_health="at_risk",
        health_score=40,
        health_summary="At risk — champion silent 10 days.",
        top_risk="Champion silent 10 days",
        risk_factors=["Champion silent 10 days", "Low engagement score"],
        next_best_action=NextBestAction(
            title="Re-engage the silent champion",
            rationale="Waiting 10 days on a reply.",
            channel="sms",
            timing="Today",
        ),
        drafted_action=DraftedAction(
            action_type="deal_coach.follow_up",
            channel="sms",
            description="Drafted re-engagement SMS to Jane Doe.",
            body="Hi Jane, checking in — want me to send next steps?",
            payload={"channel": "sms", "body": "Hi Jane"},
        ),
        signals=DealSignals(days_since_last_contact=10, awaiting_reply=True),
        generated_by="heuristic",
        generated_at=datetime.now(UTC),
    )


def _make_at_risk_response() -> AtRiskDealsResponse:
    return AtRiskDealsResponse(
        items=[
            AtRiskDeal(
                opportunity_id=OPP_ID,
                name="Acme Expansion",
                amount=12000.0,
                currency="USD",
                primary_contact_id=42,
                contact_name="Jane Doe",
                stage_name="Proposal",
                deal_health="critical",
                health_score=20,
                risk_score=80,
                top_risk="Champion silent 14 days",
                days_since_last_contact=14,
                amount_at_risk=9600.0,
            )
        ],
        total=1,
        total_amount_at_risk=9600.0,
    )


def _make_auth_app() -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    async def override_get_workspace() -> MagicMock:
        ws = MagicMock()
        ws.id = WS_ID
        ws.is_active = True
        return ws

    async def override_get_current_user() -> MagicMock:
        user = MagicMock()
        user.id = 1
        user.is_active = True
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.include_router(
        opportunities_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/opportunities",
    )
    return app


def _make_noauth_app() -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(
        opportunities_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/opportunities",
    )
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_make_auth_app()),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_make_noauth_app()),
        base_url="http://testserver",
    ) as ac:
        yield ac


class TestDealCoachAuth:
    async def test_coach_requires_auth(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/opportunities/{OPP_ID}/coach")
        assert resp.status_code == 401

    async def test_at_risk_requires_auth(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/opportunities/coaching/at-risk")
        assert resp.status_code == 401

    async def test_draft_requires_auth(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.post(
            f"/api/v1/workspaces/{WS_ID}/opportunities/{OPP_ID}/coach/draft-action"
        )
        assert resp.status_code == 401


class TestCoachCard:
    async def test_returns_card(self, client: AsyncClient) -> None:
        with patch.object(
            opportunities_module.DealCoachService,
            "coach_opportunity",
            new=AsyncMock(return_value=_make_card()),
        ):
            resp = await client.get(f"/api/v1/workspaces/{WS_ID}/opportunities/{OPP_ID}/coach")
        assert resp.status_code == 200
        body = resp.json()
        assert body["opportunity_id"] == str(OPP_ID)
        assert body["deal_health"] == "at_risk"
        assert body["top_risk"] == "Champion silent 10 days"
        assert body["next_best_action"]["channel"] == "sms"
        assert body["drafted_action"]["action_type"] == "deal_coach.follow_up"

    async def test_invalid_opportunity_uuid_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/workspaces/{WS_ID}/opportunities/not-a-uuid/coach")
        assert resp.status_code == 422


class TestAtRiskList:
    async def test_ranks_deals(self, client: AsyncClient) -> None:
        with patch.object(
            opportunities_module.DealCoachService,
            "list_at_risk",
            new=AsyncMock(return_value=_make_at_risk_response()),
        ):
            resp = await client.get(
                f"/api/v1/workspaces/{WS_ID}/opportunities/coaching/at-risk?limit=10"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["total_amount_at_risk"] == 9600.0
        assert body["items"][0]["risk_score"] == 80

    async def test_limit_validation(self, client: AsyncClient) -> None:
        resp = await client.get(
            f"/api/v1/workspaces/{WS_ID}/opportunities/coaching/at-risk?limit=0"
        )
        assert resp.status_code == 422


class TestDraftAction:
    async def test_queues_pending_action(self, client: AsyncClient) -> None:
        with patch.object(
            opportunities_module.DealCoachService,
            "queue_drafted_action",
            new=AsyncMock(
                return_value=("pending", ACTION_ID, "deal_coach.follow_up", "Drafted SMS")
            ),
        ):
            resp = await client.post(
                f"/api/v1/workspaces/{WS_ID}/opportunities/{OPP_ID}/coach/draft-action",
                json={"channel": "sms", "body": "custom"},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["decision"] == "pending"
        assert body["pending_action_id"] == str(ACTION_ID)
        assert body["action_type"] == "deal_coach.follow_up"

    async def test_rejects_unknown_fields(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"/api/v1/workspaces/{WS_ID}/opportunities/{OPP_ID}/coach/draft-action",
            json={"bogus": "field"},
        )
        assert resp.status_code == 422
