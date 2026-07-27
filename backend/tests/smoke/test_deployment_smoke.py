"""Smoke tests that verify a *live* backend deployment is healthy.

These hit a real, network-reachable backend (Railway, a staging box, or a
local ``make dev`` server) over HTTP — they do **not** boot the ASGI app in
process or touch the test database. The point is to answer one question after a
deploy: "is the thing actually up and serving correctly?"

Run them by pointing ``SMOKE_BASE_URL`` at the deployment::

    SMOKE_BASE_URL=https://<app>.railway.app uv run pytest tests/smoke -m smoke -v

When ``SMOKE_BASE_URL`` is unset the whole module is skipped, so this stays
inert during normal unit-test / CI runs.

What each probe proves:

* ``/livez``  — the process is up and the event loop is responsive.
* ``/readyz`` — startup finished and Postgres + Redis + workers are reachable.
* ``/version`` — the build endpoint responds with a SHA payload.
* ``/api/v1/auth/me`` (no token) — the API router is mounted and auth is
  enforced, i.e. protected data is not served to anonymous callers.
* Security headers on ``/livez`` — the real app middleware served the response
  rather than an upstream proxy / error page.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import pytest

SMOKE_BASE_URL = os.getenv("SMOKE_BASE_URL", "").rstrip("/")

# Generous per-request budget: a freshly deployed container may cold-start and
# the readiness probe itself allows ~2s per dependency.
_REQUEST_TIMEOUT_SECONDS = 20.0

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        not SMOKE_BASE_URL,
        reason="SMOKE_BASE_URL not set — skipping live deployment smoke tests",
    ),
]


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    """A sync HTTP client bound to the deployment base URL.

    ``follow_redirects=False`` so status assertions are exact — a 401 or 503
    must surface as itself, not get masked by a redirect chain.
    """
    with httpx.Client(
        base_url=SMOKE_BASE_URL,
        timeout=_REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={"User-Agent": "tribunal-smoke-tests"},
    ) as http_client:
        yield http_client


def test_livez_reports_ok(client: httpx.Client) -> None:
    """Liveness probe returns 200 with the canonical body."""
    response = client.get("/livez")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}


def test_readyz_is_ready(client: httpx.Client) -> None:
    """Readiness probe returns 200 and both gating dependencies pass.

    A 503 here means the deployment booted but Postgres or Redis is unhealthy —
    the body lists which one. Worker heartbeats are reported in the same payload
    but do not gate readiness; ``test_workers_are_heartbeating`` covers those.
    """
    response = client.get("/readyz")
    assert response.status_code == 200, (
        f"/readyz returned {response.status_code}, not ready: {response.text}"
    )
    body = response.json()
    assert body["status"] in {"ok", "degraded"}, body
    checks = body["checks"]
    gating = {"startup", "postgres", "redis"}
    unhealthy = {
        name: c for name, c in checks.items() if name in gating and not c.get("ok", False)
    }
    assert not unhealthy, f"unhealthy dependencies: {unhealthy}"


def test_workers_are_heartbeating(client: httpx.Client) -> None:
    """Every background worker has a fresh heartbeat.

    Deliberately separate from readiness: a wedged worker should page a human
    without giving the orchestrator a reason to restart or drain the API.
    """
    response = client.get("/workers/health")
    assert response.status_code == 200, (
        f"workers unhealthy, missing heartbeats: {response.text}"
    )
    assert response.json()["missing"] == [], response.text


def test_version_endpoint_serves_sha(client: httpx.Client) -> None:
    """The build/version endpoint responds with a non-empty SHA string."""
    response = client.get("/version")
    assert response.status_code == 200, response.text
    sha = response.json().get("sha")
    assert isinstance(sha, str) and sha, f"missing build sha: {response.text}"


def test_protected_route_rejects_anonymous(client: httpx.Client) -> None:
    """A protected API route returns 401 without a token.

    Proves the ``/api/v1`` router is mounted *and* that auth is enforced —
    i.e. the deployment is not silently serving user data to anonymous
    callers (a far worse failure than being down).
    """
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401, (
        f"expected 401 for anonymous /auth/me, got {response.status_code}: {response.text}"
    )


def test_security_headers_present(client: httpx.Client) -> None:
    """The app's security middleware stamps every response.

    If these headers are missing, the response likely came from an upstream
    error page / proxy rather than the FastAPI app itself.
    """
    response = client.get("/livez")
    assert response.status_code == 200, response.text
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert "Strict-Transport-Security" in response.headers
