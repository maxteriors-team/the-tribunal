"""Health, readiness, and version probes.

Three orthogonal endpoints follow the Kubernetes/Railway convention:

* ``/livez``  — liveness: the process is up and the event loop responsive. No
  external dependencies are checked. A 200 here only proves "I exist".
* ``/readyz`` — readiness: external dependencies (Postgres + Redis) reachable
  within a 2-second budget. Returns 503 if either probe fails or times out so
  load balancers can drain the instance.
* ``/version`` — build identifier sourced from the ``RAILWAY_GIT_COMMIT_SHA``
  environment variable (falls back to ``"unknown"``).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db.redis import get_redis
from app.db.session import AsyncSessionLocal

router = APIRouter()
logger = structlog.get_logger()

# Per-dependency probe budget. The overall request still completes in roughly
# this window because the two checks run concurrently via ``asyncio.gather``.
_PROBE_TIMEOUT_SECONDS = 2.0


async def _check_postgres() -> tuple[bool, str | None]:
    """Run ``SELECT 1`` against Postgres with a hard timeout."""
    try:
        async def _run() -> None:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))

        await asyncio.wait_for(_run(), timeout=_PROBE_TIMEOUT_SECONDS)
        return True, None
    except TimeoutError:
        return False, "timeout"
    except Exception as exc:  # noqa: BLE001 — surface any driver/connection error
        return False, type(exc).__name__


async def _check_redis() -> tuple[bool, str | None]:
    """Run ``PING`` against Redis with a hard timeout."""
    try:
        async def _run() -> None:
            client = await get_redis()
            # ``redis.asyncio.Redis.ping`` is typed as returning ``Awaitable[bool]
            # | bool`` in some stub versions; awaiting an already-resolved bool
            # would raise, so route through ``asyncio.ensure_future`` only when
            # we get a coroutine back.
            result = client.ping()
            if asyncio.iscoroutine(result):
                await result

        await asyncio.wait_for(_run(), timeout=_PROBE_TIMEOUT_SECONDS)
        return True, None
    except TimeoutError:
        return False, "timeout"
    except Exception as exc:  # noqa: BLE001 — surface any driver/connection error
        return False, type(exc).__name__


@router.get("/livez", tags=["Health"])
async def livez() -> dict[str, str]:
    """Liveness probe — process is up.

    Intentionally does not touch external services. Use ``/readyz`` for that.
    """
    return {"status": "ok"}


@router.get("/readyz", tags=["Health"])
async def readyz(response: Response) -> dict[str, Any]:
    """Readiness probe — Postgres + Redis reachable within 2s each.

    Returns HTTP 503 when either dependency fails or times out so upstream
    load balancers stop sending traffic to this instance.
    """
    postgres_result, redis_result = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
    )
    postgres_ok, postgres_err = postgres_result
    redis_ok, redis_err = redis_result

    checks = {
        "postgres": {"ok": postgres_ok, "error": postgres_err},
        "redis": {"ok": redis_ok, "error": redis_err},
    }

    if not (postgres_ok and redis_ok):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning(
            "readyz_failed",
            postgres_ok=postgres_ok,
            postgres_err=postgres_err,
            redis_ok=redis_ok,
            redis_err=redis_err,
        )
        return {"status": "unavailable", "checks": checks}

    return {"status": "ok", "checks": checks}


@router.get("/version", tags=["Health"])
async def version() -> dict[str, str]:
    """Return the build's git SHA from ``RAILWAY_GIT_COMMIT_SHA``."""
    sha = os.getenv("RAILWAY_GIT_COMMIT_SHA", "unknown")
    return {"sha": sha}
