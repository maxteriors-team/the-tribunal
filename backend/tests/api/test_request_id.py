"""Tests for the request-ID middleware end-to-end behaviour.

These tests build a tiny FastAPI app wired up with the real
:class:`app.main.RequestIDMiddleware` so we can assert on round-trip
behaviour without needing a live database, Redis, or workers.

What we verify:

* A request that omits ``X-Request-ID`` still gets one back on the response
  (i.e. middleware generates a ULID).
* A well-formed inbound ``X-Request-ID`` is echoed back verbatim.
* A malformed inbound ``X-Request-ID`` is *replaced* with a generated ULID
  (the middleware must not blindly trust caller input).
* ``request.state.request_id`` matches the response header for any given
  request (so route handlers and middleware agree).
* The ID is also bound into structlog's contextvars while the handler runs
  (every log line during the request automatically carries it).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import structlog
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.api.v1.health import router as health_router
from app.core.request_id import generate_ulid, sanitize_request_id
from app.main import REQUEST_ID_HEADER, RequestIDMiddleware

# ULID format: 26 chars of Crockford base32 (digits + uppercase minus I, L, O, U).
_ULID_RE = re.compile(r"^[0-9ABCDEFGHJKMNPQRSTVWXYZ]{26}$")


@asynccontextmanager
async def _noop_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Skip worker / DB startup for these unit-style tests."""
    yield


def _make_app() -> FastAPI:
    """Build a minimal app exercising the real middleware.

    We mount the ``/livez`` and ``/readyz`` health routes plus a custom
    ``/echo-request-id`` endpoint that reflects what the middleware stored on
    ``request.state`` and the current structlog contextvars. This lets us
    assert on the middleware's three contracts (header, request.state,
    contextvars) from a single response.
    """
    app = FastAPI(lifespan=_noop_lifespan)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health_router)

    @app.get("/echo-request-id")
    async def echo(request: Request) -> dict[str, str | None]:
        ctx = structlog.contextvars.get_contextvars()
        return {
            "state_request_id": getattr(request.state, "request_id", None),
            "contextvar_request_id": ctx.get("request_id"),
        }

    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


class TestGeneratedRequestID:
    """When the client doesn't send X-Request-ID, the middleware mints one."""

    async def test_response_includes_request_id_header(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/livez")
        assert response.status_code == 200
        assert REQUEST_ID_HEADER in {k.lower() for k in response.headers}

    async def test_generated_id_is_a_ulid(self, client: AsyncClient) -> None:
        response = await client.get("/livez")
        request_id = response.headers["x-request-id"]
        assert _ULID_RE.match(request_id), f"expected ULID, got {request_id!r}"

    async def test_each_request_gets_a_fresh_id(self, client: AsyncClient) -> None:
        first = (await client.get("/livez")).headers["x-request-id"]
        second = (await client.get("/livez")).headers["x-request-id"]
        assert first != second


class TestInboundRequestIDRoundTrip:
    """A well-formed inbound X-Request-ID is propagated unchanged."""

    async def test_well_formed_id_round_trips(self, client: AsyncClient) -> None:
        supplied = "trace-abc-123_456.789"
        response = await client.get(
            "/livez", headers={"X-Request-ID": supplied}
        )
        assert response.status_code == 200
        assert response.headers["x-request-id"] == supplied

    async def test_ulid_inbound_round_trips(self, client: AsyncClient) -> None:
        # A caller-generated ULID is the common case for service-to-service
        # traffic that's already been tagged at the edge.
        supplied = generate_ulid()
        response = await client.get(
            "/livez", headers={"X-Request-ID": supplied}
        )
        assert response.headers["x-request-id"] == supplied

    async def test_state_and_header_agree(self, client: AsyncClient) -> None:
        supplied = generate_ulid()
        response = await client.get(
            "/echo-request-id", headers={"X-Request-ID": supplied}
        )
        body = response.json()
        assert response.headers["x-request-id"] == supplied
        assert body["state_request_id"] == supplied

    async def test_contextvar_bound_during_request(
        self, client: AsyncClient
    ) -> None:
        supplied = generate_ulid()
        response = await client.get(
            "/echo-request-id", headers={"X-Request-ID": supplied}
        )
        body = response.json()
        # The middleware must bind ``request_id`` into structlog's contextvars
        # so log lines emitted inside the handler are correlated automatically.
        assert body["contextvar_request_id"] == supplied


class TestMalformedInboundIDsAreReplaced:
    """Defence-in-depth: never trust caller-supplied header values blindly."""

    async def test_overlong_id_is_replaced(self, client: AsyncClient) -> None:
        # 200 chars is well past our 128-char cap.
        supplied = "a" * 200
        response = await client.get(
            "/livez", headers={"X-Request-ID": supplied}
        )
        returned = response.headers["x-request-id"]
        assert returned != supplied
        assert _ULID_RE.match(returned)

    async def test_id_with_disallowed_chars_is_replaced(
        self, client: AsyncClient
    ) -> None:
        supplied = "has spaces and <html>"
        response = await client.get(
            "/livez", headers={"X-Request-ID": supplied}
        )
        returned = response.headers["x-request-id"]
        assert returned != supplied
        assert _ULID_RE.match(returned)

    async def test_empty_id_is_replaced(self, client: AsyncClient) -> None:
        response = await client.get("/livez", headers={"X-Request-ID": "   "})
        returned = response.headers["x-request-id"]
        assert _ULID_RE.match(returned)


class TestContextvarsLeakageGuard:
    """The middleware must not leak request_id into the next request."""

    async def test_contextvars_cleared_after_request(
        self, client: AsyncClient
    ) -> None:
        await client.get("/livez", headers={"X-Request-ID": generate_ulid()})
        # After the response returns and the middleware's ``finally`` runs,
        # the test task should observe no lingering request_id.
        assert "request_id" not in structlog.contextvars.get_contextvars()


class TestUlidGenerator:
    """Unit tests for the ULID helper itself."""

    def test_generate_ulid_format(self) -> None:
        for _ in range(20):
            assert _ULID_RE.match(generate_ulid())

    def test_sanitize_returns_ulid_for_none(self) -> None:
        assert _ULID_RE.match(sanitize_request_id(None))

    def test_sanitize_returns_ulid_for_empty(self) -> None:
        assert _ULID_RE.match(sanitize_request_id(""))
        assert _ULID_RE.match(sanitize_request_id("   "))

    def test_sanitize_accepts_well_formed(self) -> None:
        good = "abc-123_DEF.456"
        assert sanitize_request_id(good) == good

    def test_sanitize_replaces_overlong(self) -> None:
        result = sanitize_request_id("x" * 1000)
        assert _ULID_RE.match(result)

    def test_sanitize_replaces_bad_chars(self) -> None:
        result = sanitize_request_id("has spaces")
        assert _ULID_RE.match(result)
