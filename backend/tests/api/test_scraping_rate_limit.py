"""API-level tests for per-workspace Google Places rate limiting.

These tests wire the real route handlers in ``app/api/v1/scraping.py`` and
``app/api/v1/find_leads_ai.py`` to a stub limiter and assert the routes
surface 429 with a ``Retry-After`` header when the workspace cap is hit.

Auth and DB are stubbed out with ``dependency_overrides`` so the test stays
focused on the rate-limit branch and doesn't require Postgres/Redis.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.v1.router import api_router


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_test_app() -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(api_router, prefix="/api/v1")

    fake_user = MagicMock()
    fake_user.id = uuid.uuid4()
    fake_user.is_active = True

    fake_workspace = MagicMock()
    fake_workspace.id = uuid.uuid4()
    fake_workspace.is_active = True

    async def _override_user() -> MagicMock:
        return fake_user

    async def _override_db() -> AsyncMock:
        return AsyncMock()

    async def _override_workspace() -> MagicMock:
        return fake_workspace

    async def _override_membership() -> MagicMock:
        # The lead-sourcing routers require ``outreach:write``. This file tests
        # rate limiting, not authorization, so the owner role preserves the
        # access it was written against;
        # ``tests/api/test_technician_surface_probe.py`` owns role behaviour.
        membership = MagicMock()
        membership.role = "owner"
        membership.workspace_id = fake_workspace.id
        return membership

    app.dependency_overrides[deps.get_current_user] = _override_user
    app.dependency_overrides[deps.get_db] = _override_db
    app.dependency_overrides[deps.get_workspace] = _override_workspace
    app.dependency_overrides[deps.get_membership] = _override_membership

    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


def _raise_429(seconds: int = 1234) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Hourly search limit reached for this workspace.",
        headers={"Retry-After": str(seconds)},
    )


class TestScrapingSearchRateLimit:
    """``POST /workspaces/{id}/scraping/search`` is capped per workspace.

    ``scraping.py`` calls ``get_workspace()`` directly (not via ``Depends``)
    so we patch the imported name in that module rather than relying on
    FastAPI's ``dependency_overrides``.
    """

    async def test_returns_429_with_retry_after_when_limit_hit(
        self, client: AsyncClient
    ) -> None:
        async def block(_: uuid.UUID) -> None:
            raise _raise_429(seconds=42)

        async def fake_get_workspace(*_args: object, **_kwargs: object) -> MagicMock:
            ws = MagicMock()
            ws.id = uuid.UUID(WORKSPACE_ID)
            return ws

        with (
            patch(
                "app.api.v1.scraping.get_workspace",
                side_effect=fake_get_workspace,
            ),
            patch(
                "app.api.v1.scraping.enforce_scraping_rate_limit",
                side_effect=block,
            ),
        ):
            resp = await client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/scraping/search",
                json={"query": "dentists in austin", "max_results": 10},
            )

        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "42"
        assert "limit" in resp.json()["detail"].lower()

    async def test_does_not_call_google_places_when_limited(
        self, client: AsyncClient
    ) -> None:
        """Cost-control: a 429 must short-circuit the paid upstream call."""

        async def block(_: uuid.UUID) -> None:
            raise _raise_429()

        async def fake_get_workspace(*_args: object, **_kwargs: object) -> MagicMock:
            ws = MagicMock()
            ws.id = uuid.UUID(WORKSPACE_ID)
            return ws

        fake_service_instance = AsyncMock()
        fake_service_instance.search_businesses = AsyncMock(return_value=[])
        fake_service_instance.close = AsyncMock()

        with (
            patch(
                "app.api.v1.scraping.get_workspace",
                side_effect=fake_get_workspace,
            ),
            patch(
                "app.api.v1.scraping.enforce_scraping_rate_limit",
                side_effect=block,
            ),
            patch(
                "app.api.v1.scraping.GooglePlacesService",
                return_value=fake_service_instance,
            ) as service_cls,
        ):
            resp = await client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/scraping/search",
                json={"query": "dentists", "max_results": 5},
            )

        assert resp.status_code == 429
        service_cls.assert_not_called()
        fake_service_instance.search_businesses.assert_not_called()


class TestFindLeadsAISearchRateLimit:
    """``POST /find-leads-ai/...search`` shares the same per-workspace cap."""

    async def test_returns_429_with_retry_after_when_limit_hit(
        self, client: AsyncClient
    ) -> None:
        async def block(_: uuid.UUID) -> None:
            raise _raise_429(seconds=900)

        with patch(
            "app.api.v1.find_leads_ai.enforce_scraping_rate_limit",
            side_effect=block,
        ):
            # Route is mounted at /workspaces/{workspace_id}/find-leads-ai
            # per the router config in app/api/v1/router.py.
            resp = await client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/find-leads-ai/search",
                json={"query": "plumbers in dallas", "max_results": 10},
            )

        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "900"

    async def test_does_not_call_google_places_when_limited(
        self, client: AsyncClient
    ) -> None:
        async def block(_: uuid.UUID) -> None:
            raise _raise_429()

        fake_service_instance = AsyncMock()
        fake_service_instance.search_businesses = AsyncMock(return_value=[])
        fake_service_instance.close = AsyncMock()

        with (
            patch(
                "app.api.v1.find_leads_ai.enforce_scraping_rate_limit",
                side_effect=block,
            ),
            patch(
                "app.api.v1.find_leads_ai.GooglePlacesService",
                return_value=fake_service_instance,
            ) as service_cls,
        ):
            resp = await client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/find-leads-ai/search",
                json={"query": "plumbers", "max_results": 5},
            )

        assert resp.status_code == 429
        service_cls.assert_not_called()
        fake_service_instance.search_businesses.assert_not_called()


class TestProviderNotConfigured:
    """A missing Google Places key yields a machine-readable 503 code.

    The route returns a structured ``provider_not_configured`` detail so the UI
    can render an actionable "add a key in Settings" banner instead of a generic
    "search failed" toast (distinct from an empty / no-results response).
    """

    async def test_search_returns_provider_not_configured_code(
        self, client: AsyncClient
    ) -> None:
        from app.services.scraping.google_places import GooglePlacesNotConfiguredError

        async def allow(_: uuid.UUID) -> None:
            return None

        async def fake_get_workspace(*_args: object, **_kwargs: object) -> MagicMock:
            ws = MagicMock()
            ws.id = uuid.UUID(WORKSPACE_ID)
            return ws

        fake_service_instance = AsyncMock()
        fake_service_instance.search_businesses = AsyncMock(
            side_effect=GooglePlacesNotConfiguredError("Google Places API key not configured")
        )
        fake_service_instance.close = AsyncMock()

        with (
            patch(
                "app.api.v1.scraping.get_workspace",
                side_effect=fake_get_workspace,
            ),
            patch(
                "app.api.v1.scraping.enforce_scraping_rate_limit",
                side_effect=allow,
            ),
            patch(
                "app.api.v1.scraping.GooglePlacesService",
                return_value=fake_service_instance,
            ),
        ):
            resp = await client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/scraping/search",
                json={"query": "plumbers in austin", "max_results": 10},
            )

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["code"] == "provider_not_configured"
        assert detail["details"]["provider"] == "google_places"
        # The paid client was still closed even on the error path.
        fake_service_instance.close.assert_awaited_once()


class TestUnderLimitPassesThrough:
    """When the limiter is satisfied, the route proceeds to Google Places."""

    async def test_scraping_search_proceeds_when_under_limit(
        self, client: AsyncClient
    ) -> None:
        async def allow(_: uuid.UUID) -> None:
            return None

        async def fake_get_workspace(*_args: object, **_kwargs: object) -> MagicMock:
            ws = MagicMock()
            ws.id = uuid.UUID(WORKSPACE_ID)
            return ws

        fake_service_instance = AsyncMock()
        fake_service_instance.search_businesses = AsyncMock(return_value=[])
        fake_service_instance.close = AsyncMock()

        with (
            patch(
                "app.api.v1.scraping.get_workspace",
                side_effect=fake_get_workspace,
            ),
            patch(
                "app.api.v1.scraping.enforce_scraping_rate_limit",
                side_effect=allow,
            ),
            patch(
                "app.api.v1.scraping.GooglePlacesService",
                return_value=fake_service_instance,
            ),
        ):
            resp = await client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/scraping/search",
                json={"query": "dentists", "max_results": 5},
            )

        assert resp.status_code == 200
        fake_service_instance.search_businesses.assert_awaited_once()

    async def test_find_leads_ai_search_proceeds_when_under_limit(
        self, client: AsyncClient
    ) -> None:
        async def allow(_: uuid.UUID) -> None:
            return None

        fake_service_instance = AsyncMock()
        fake_service_instance.search_businesses = AsyncMock(return_value=[])
        fake_service_instance.close = AsyncMock()

        with (
            patch(
                "app.api.v1.find_leads_ai.enforce_scraping_rate_limit",
                side_effect=allow,
            ),
            patch(
                "app.api.v1.find_leads_ai.GooglePlacesService",
                return_value=fake_service_instance,
            ),
        ):
            resp = await client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/find-leads-ai/search",
                json={"query": "plumbers", "max_results": 5},
            )

        assert resp.status_code == 200
        fake_service_instance.search_businesses.assert_awaited_once()
