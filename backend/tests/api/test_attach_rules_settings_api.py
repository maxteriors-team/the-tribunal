"""Contract tests for the attach-rule settings endpoints.

Covers the operator-configurable half of the cross-sell prompt: a PUT/GET
round-trips edited rules, a partial update merges instead of clobbering, a
corrupt stored blob still reads as usable defaults rather than 500ing, an
invalid rule is rejected at the edge, and an unauthenticated caller is refused.

DB-free via dependency overrides + a stateful fake workspace whose ``settings``
dict persists across requests, mirroring
:mod:`tests.api.test_proposal_template_settings_api`.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import settings as settings_module

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_workspace(settings: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=WS_ID, name="Maxteriors", is_active=True, settings=settings or {})


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
    app.dependency_overrides[get_membership] = lambda: SimpleNamespace(
        role="owner", workspace_id=WS_ID
    )
    app.include_router(settings_module.router, prefix="/api/v1")
    return app


def _client(workspace: SimpleNamespace) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=_auth_app(workspace)),
        base_url="http://testserver",
    )


@pytest.fixture
def workspace() -> SimpleNamespace:
    return _make_workspace()


@pytest.fixture
async def auth_client(workspace: SimpleNamespace) -> AsyncIterator[AsyncClient]:
    async with _client(workspace) as ac:
        yield ac


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/attach-rules"


async def test_get_returns_advisory_defaults(auth_client: AsyncClient) -> None:
    """A workspace that configured nothing still gets the prompt, softly."""
    resp = await auth_client.get(_url())

    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["rules"]
    # Ship advisory: the operator watches attach rate before tightening.
    assert {rule["mode"] for rule in body["rules"]} == {"advisory"}
    assert "{primary}" in body["prompt_template"]
    assert "Customer declined" in body["dismissal_reasons"]


async def test_put_then_get_round_trips_rules(auth_client: AsyncClient) -> None:
    resp = await auth_client.put(
        _url(),
        json={
            "rules": [
                {
                    "primary_category": "roof",
                    "suggested_categories": ["gutters"],
                    "mode": "blocking",
                }
            ]
        },
    )
    assert resp.status_code == 200

    body = (await auth_client.get(_url())).json()
    assert body["rules"] == [
        {
            "primary_category": "roof",
            "suggested_categories": ["gutters"],
            "mode": "blocking",
        }
    ]


async def test_partial_update_merges_without_clobbering(
    auth_client: AsyncClient,
) -> None:
    await auth_client.put(
        _url(),
        json={"rules": [{"primary_category": "siding", "suggested_categories": ["trim"]}]},
    )
    # Editing only the copy must not wipe the rules the operator just wrote.
    await auth_client.put(_url(), json={"prompt_template": "Ask about {primary} add-ons."})

    body = (await auth_client.get(_url())).json()
    assert body["prompt_template"] == "Ask about {primary} add-ons."
    assert body["rules"][0]["primary_category"] == "siding"


async def test_blank_and_duplicate_categories_are_cleaned(
    auth_client: AsyncClient,
) -> None:
    """Sloppy operator input is cleaned at the edge, not rejected."""
    await auth_client.put(
        _url(),
        json={
            "rules": [
                {
                    "primary_category": "  roof  ",
                    "suggested_categories": ["Gutters", "", "  ", "gutters"],
                }
            ]
        },
    )

    rule = (await auth_client.get(_url())).json()["rules"][0]
    assert rule["primary_category"] == "roof"
    assert rule["suggested_categories"] == ["Gutters"]


async def test_invalid_mode_rejected(auth_client: AsyncClient) -> None:
    resp = await auth_client.put(
        _url(),
        json={
            "rules": [
                {
                    "primary_category": "roof",
                    "suggested_categories": ["gutters"],
                    "mode": "nag-forever",
                }
            ]
        },
    )
    assert resp.status_code == 422


async def test_empty_primary_category_rejected(auth_client: AsyncClient) -> None:
    """A rule with no job type can never fire; refuse it rather than store it."""
    resp = await auth_client.put(
        _url(), json={"rules": [{"primary_category": "", "suggested_categories": ["x"]}]}
    )
    assert resp.status_code == 422


async def test_corrupt_blob_reads_as_defaults_not_a_500() -> None:
    """A hand-edited settings row must not 500 the settings page.

    This endpoint and the quote save path share one reader, so this is also the
    guarantee that a broken config cannot stop a rep saving a quote.
    """
    workspace = _make_workspace(
        {"attach_rules": {"rules": "not-a-list", "enabled": {"nope": True}}}
    )

    async with _client(workspace) as ac:
        resp = await ac.get(_url())

    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


async def test_unauthenticated_rejected() -> None:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    # Only the db is overridden; the real auth dependencies run and reject the
    # tokenless request before any workspace lookup.
    app.dependency_overrides[get_db] = override_get_db
    app.include_router(settings_module.router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        resp = await ac.get(_url())
    assert resp.status_code in (401, 403)
