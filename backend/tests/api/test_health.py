"""Tests for the health probe endpoints.

Exercises GET ``/livez``, ``/readyz``, and ``/version`` using a mocked app
lifespan that bypasses worker startup and Redis/database initialization. The
readiness checks themselves are patched so we can simulate dependency failures
without a live Postgres or Redis.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.api.webhooks.calcom import router as calcom_webhook_router
from app.api.webhooks.telnyx import router as telnyx_webhook_router
from app.websockets.voice_bridge import router as voice_bridge_router
from app.websockets.voice_test import router as voice_test_router


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan that skips workers, Redis, and DB setup."""
    yield


def _make_test_app() -> FastAPI:
    """Create a minimal FastAPI app with all routes but no worker startup.

    Pins ``app.state.ready = True`` so ``/readyz`` doesn't short-circuit to
    503 — ``ASGITransport`` doesn't fire FastAPI lifespan events, so the
    flag must be set explicitly here to mirror a fully-booted process.
    """
    app = FastAPI(lifespan=_test_lifespan)
    app.state.ready = True

    # Register all the same routers as the real app
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(health_router)
    app.include_router(calcom_webhook_router, prefix="/api/webhooks")
    app.include_router(telnyx_webhook_router, prefix="/api/webhooks")
    app.include_router(voice_bridge_router)
    app.include_router(voice_test_router)

    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client bound to the test app."""
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


class TestLivez:
    """GET /livez — pure process-up probe."""

    async def test_livez_returns_200(self, client: AsyncClient) -> None:
        response = await client.get("/livez")
        assert response.status_code == 200

    async def test_livez_body(self, client: AsyncClient) -> None:
        response = await client.get("/livez")
        assert response.json() == {"status": "ok"}

    async def test_livez_does_not_touch_postgres_or_redis(self, client: AsyncClient) -> None:
        """Liveness must not depend on external services."""
        with (
            patch(
                "app.api.v1.health._check_postgres",
                new=AsyncMock(side_effect=AssertionError("should not be called")),
            ),
            patch(
                "app.api.v1.health._check_redis",
                new=AsyncMock(side_effect=AssertionError("should not be called")),
            ),
        ):
            response = await client.get("/livez")
        assert response.status_code == 200


class TestReadyz:
    """GET /readyz — Postgres + Redis probe."""

    async def test_readyz_returns_200_when_both_ok(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.health._check_postgres",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "app.api.v1.health._check_redis",
                new=AsyncMock(return_value=(True, None)),
            ),
        ):
            response = await client.get("/readyz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["checks"]["postgres"]["ok"] is True
        assert body["checks"]["redis"]["ok"] is True

    async def test_readyz_returns_503_when_postgres_fails(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.health._check_postgres",
                new=AsyncMock(return_value=(False, "OperationalError")),
            ),
            patch(
                "app.api.v1.health._check_redis",
                new=AsyncMock(return_value=(True, None)),
            ),
        ):
            response = await client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["checks"]["postgres"]["ok"] is False
        assert body["checks"]["postgres"]["error"] == "OperationalError"
        assert body["checks"]["redis"]["ok"] is True

    async def test_readyz_returns_503_when_redis_fails(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.health._check_postgres",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "app.api.v1.health._check_redis",
                new=AsyncMock(return_value=(False, "ConnectionError")),
            ),
        ):
            response = await client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["checks"]["redis"]["ok"] is False
        assert body["checks"]["redis"]["error"] == "ConnectionError"

    async def test_readyz_returns_503_when_both_fail(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.health._check_postgres",
                new=AsyncMock(return_value=(False, "timeout")),
            ),
            patch(
                "app.api.v1.health._check_redis",
                new=AsyncMock(return_value=(False, "timeout")),
            ),
        ):
            response = await client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["checks"]["postgres"]["error"] == "timeout"
        assert body["checks"]["redis"]["error"] == "timeout"

    async def test_readyz_returns_503_when_worker_heartbeat_missing(
        self, client: AsyncClient
    ) -> None:
        """Missing heartbeat ⇒ worker is wedged ⇒ /readyz flips to 503."""
        with (
            patch(
                "app.api.v1.health._check_postgres",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "app.api.v1.health._check_redis",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "app.api.v1.health._check_worker_heartbeats",
                new=AsyncMock(return_value=(False, {"campaign_worker": False}, None)),
            ),
        ):
            response = await client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["checks"]["workers"]["ok"] is False
        assert body["checks"]["workers"]["heartbeats"] == {"campaign_worker": False}

    async def test_readyz_returns_200_when_all_heartbeats_present(
        self, client: AsyncClient
    ) -> None:
        """All workers have fresh heartbeats ⇒ /readyz passes."""
        with (
            patch(
                "app.api.v1.health._check_postgres",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "app.api.v1.health._check_redis",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "app.api.v1.health._check_worker_heartbeats",
                new=AsyncMock(return_value=(True, {"campaign_worker": True}, None)),
            ),
        ):
            response = await client.get("/readyz")
        assert response.status_code == 200
        body = response.json()
        assert body["checks"]["workers"]["ok"] is True


class TestPostgresProbe:
    """Unit tests for the Postgres probe helper."""

    async def test_postgres_probe_reports_timeout(self) -> None:
        """A slow query past the 2s budget reports ``timeout``."""
        import asyncio

        from app.api.v1 import health

        async def _slow_session() -> AsyncMock:
            await asyncio.sleep(10)
            return AsyncMock()

        # Force the timeout path by patching the timeout constant to something
        # tiny and the session factory to a slow no-op.
        slow_session = AsyncMock()
        slow_session.__aenter__ = AsyncMock(side_effect=_slow_session)
        slow_session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.object(health, "_PROBE_TIMEOUT_SECONDS", 0.01),
            patch.object(health, "AsyncSessionLocal", return_value=slow_session),
        ):
            ok, err = await health._check_postgres()
        assert ok is False
        assert err == "timeout"

    async def test_postgres_probe_reports_error_class(self) -> None:
        """A driver-level failure surfaces the exception class name."""
        from app.api.v1 import health

        class FakeOperationalError(Exception):
            pass

        broken_session = AsyncMock()
        broken_session.__aenter__ = AsyncMock(side_effect=FakeOperationalError("boom"))
        broken_session.__aexit__ = AsyncMock(return_value=None)

        with patch.object(health, "AsyncSessionLocal", return_value=broken_session):
            ok, err = await health._check_postgres()
        assert ok is False
        assert err == "FakeOperationalError"


class TestRedisProbe:
    """Unit tests for the Redis probe helper."""

    async def test_redis_probe_reports_timeout(self) -> None:
        import asyncio

        from app.api.v1 import health

        async def _slow_get_redis() -> AsyncMock:
            await asyncio.sleep(10)
            return AsyncMock()

        with (
            patch.object(health, "_PROBE_TIMEOUT_SECONDS", 0.01),
            patch.object(health, "get_redis", new=_slow_get_redis),
        ):
            ok, err = await health._check_redis()
        assert ok is False
        assert err == "timeout"

    async def test_redis_probe_reports_error_class(self) -> None:
        from app.api.v1 import health

        class FakeConnectionError(Exception):
            pass

        async def _broken_get_redis() -> AsyncMock:
            raise FakeConnectionError("nope")

        with patch.object(health, "get_redis", new=_broken_get_redis):
            ok, err = await health._check_redis()
        assert ok is False
        assert err == "FakeConnectionError"

    async def test_redis_probe_ok_when_ping_succeeds(self) -> None:
        from app.api.v1 import health

        fake_client = AsyncMock()
        fake_client.ping = AsyncMock(return_value=True)

        async def _ok_get_redis() -> AsyncMock:
            return fake_client

        with patch.object(health, "get_redis", new=_ok_get_redis):
            ok, err = await health._check_redis()
        assert ok is True
        assert err is None
        fake_client.ping.assert_awaited_once()


class TestWorkerHeartbeatProbe:
    """Unit tests for the worker-heartbeat probe helper."""

    async def test_empty_labels_short_circuits(self) -> None:
        """Pre-startup (no running workers) returns ok without touching Redis."""
        from app.api.v1 import health

        with (
            patch.object(health, "_expected_worker_labels", return_value=[]),
            patch.object(
                health,
                "get_redis",
                new=AsyncMock(side_effect=AssertionError("Redis must not be touched")),
            ),
        ):
            ok, per_worker, err = await health._check_worker_heartbeats()
        assert ok is True
        assert per_worker == {}
        assert err is None

    async def test_many_workers_use_single_round_trip(self) -> None:
        """All heartbeat keys are fetched in one MGET, not a per-worker fan-out.

        This is the deploy-blocking regression: a fan-out of one ``exists()``
        per worker borrowed one Redis connection each, exhausting the bounded
        pool (``MaxConnectionsError``) once the worker count climbed to 24.
        A single ``MGET`` borrows at most one connection regardless of count.
        """
        from app.api.v1 import health
        from app.workers.base import heartbeat_key

        labels = [f"worker_{i}" for i in range(24)]

        fake_client = AsyncMock()
        # MGET returns values ordered identically to keys; non-None ⇒ present.
        fake_client.mget = AsyncMock(return_value=["1700000000"] * len(labels))
        fake_client.exists = AsyncMock(
            side_effect=AssertionError("per-worker exists() fan-out must not be used")
        )

        async def _get_redis() -> AsyncMock:
            return fake_client

        with (
            patch.object(health, "_expected_worker_labels", return_value=labels),
            patch.object(health, "get_redis", new=_get_redis),
        ):
            ok, per_worker, err = await health._check_worker_heartbeats()

        assert ok is True
        assert err is None
        assert per_worker == dict.fromkeys(labels, True)
        # Exactly one Redis round-trip for all 24 workers.
        fake_client.mget.assert_awaited_once_with([heartbeat_key(label) for label in labels])

    async def test_missing_keys_map_to_per_worker_false(self) -> None:
        """A ``None`` value (missing/expired key) flips that worker to False."""
        from app.api.v1 import health

        labels = ["alpha", "bravo", "charlie"]

        fake_client = AsyncMock()
        fake_client.mget = AsyncMock(return_value=["1700000000", None, "1700000001"])

        async def _get_redis() -> AsyncMock:
            return fake_client

        with (
            patch.object(health, "_expected_worker_labels", return_value=labels),
            patch.object(health, "get_redis", new=_get_redis),
        ):
            ok, per_worker, err = await health._check_worker_heartbeats()

        assert ok is False
        assert err is None
        assert per_worker == {"alpha": True, "bravo": False, "charlie": True}

    async def test_redis_error_reports_all_workers_down(self) -> None:
        """A Redis failure surfaces the error class with all workers False."""
        from app.api.v1 import health

        labels = ["alpha", "bravo"]

        class FakeMaxConnectionsError(Exception):
            pass

        fake_client = AsyncMock()
        fake_client.mget = AsyncMock(side_effect=FakeMaxConnectionsError("pool exhausted"))

        async def _get_redis() -> AsyncMock:
            return fake_client

        with (
            patch.object(health, "_expected_worker_labels", return_value=labels),
            patch.object(health, "get_redis", new=_get_redis),
        ):
            ok, per_worker, err = await health._check_worker_heartbeats()

        assert ok is False
        assert err == "FakeMaxConnectionsError"
        assert per_worker == dict.fromkeys(labels, False)


class TestVersion:
    """GET /version — git SHA from RAILWAY_GIT_COMMIT_SHA."""

    async def test_version_returns_sha_from_env(self, client: AsyncClient) -> None:
        with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "abc123def"}):
            response = await client.get("/version")
        assert response.status_code == 200
        assert response.json() == {"sha": "abc123def"}

    async def test_version_defaults_to_unknown_when_env_missing(self, client: AsyncClient) -> None:
        env = {k: v for k, v in os.environ.items() if k != "RAILWAY_GIT_COMMIT_SHA"}
        with patch.dict(os.environ, env, clear=True):
            response = await client.get("/version")
        assert response.status_code == 200
        assert response.json() == {"sha": "unknown"}


class TestAuthEndpointErrors:
    """Tests for auth endpoint error responses (no DB needed).

    These ride along on the same lightweight test app used for the health
    probes because they only exercise error paths that never reach the
    database.
    """

    async def test_login_invalid_credentials_returns_401(self, client: AsyncClient) -> None:
        """Login with invalid credentials returns 401 when DB returns no user.

        The DB is not running in tests, so we mock it to return None for the
        user lookup, which exercises the 401 path.
        """
        from unittest.mock import MagicMock

        from sqlalchemy.engine import Result

        mock_result = MagicMock(spec=Result)
        mock_result.scalar_one_or_none.return_value = None
        # Lockout count query returns 0 (no prior failures) so the lockout
        # short-circuit isn't tripped and we exercise the wrong-credentials
        # 401 path.
        mock_result.scalar.return_value = 0

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        # ``Session.add`` is synchronous on the real AsyncSession.
        mock_db.add = MagicMock(return_value=None)

        # Patch the rate limit check to be a no-op and the DB session
        with (
            patch("app.api.v1.auth._check_auth_rate_limit", new=AsyncMock()),
            patch("app.db.session.AsyncSessionLocal", return_value=mock_db),
        ):
            response = await client.post(
                "/api/v1/auth/login",
                data={"username": "nobody@example.com", "password": "wrong"},
            )

        assert response.status_code == 401

    async def test_register_missing_body_returns_422(self, client: AsyncClient) -> None:
        """Register with no body returns 422 Unprocessable Entity."""
        response = await client.post("/api/v1/auth/register", json={})
        assert response.status_code == 422

    async def test_me_without_token_returns_401(self, client: AsyncClient) -> None:
        """GET /auth/me without Authorization header returns 401."""
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401
