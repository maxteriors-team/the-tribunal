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
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.db.redis import get_redis
from app.db.session import AsyncSessionLocal
from app.workers import ALL_REGISTRIES
from app.workers.base import heartbeat_key

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


def _expected_worker_labels() -> list[str]:
    """Return the component names of workers that are expected to be running.

    A worker only counts toward the heartbeat check after its registry has
    produced a live instance — i.e. once :func:`start_all_workers` has
    completed. During cold start the registries are empty and this returns
    an empty list, so ``/readyz`` won't spuriously fail before workers boot.
    """
    labels: list[str] = []
    for registry in ALL_REGISTRIES:
        instance = registry.get()
        if instance is None:
            continue
        labels.append(instance.COMPONENT_NAME or instance.__class__.__name__.lower())
    return labels


async def _check_worker_heartbeats() -> tuple[bool, dict[str, bool], str | None]:
    """Verify every running worker has a fresh heartbeat key in Redis.

    Returns ``(ok, per_worker, error)`` where ``per_worker`` maps each
    expected worker's label to whether its heartbeat key currently exists.
    A missing or expired key means the worker loop hasn't completed a cycle
    within ``HEARTBEAT_TTL_MULTIPLIER * poll_interval`` seconds and is
    presumed wedged.
    """
    labels = _expected_worker_labels()
    if not labels:
        # Pre-startup or test contexts — nothing to check.
        return True, {}, None

    try:

        async def _run() -> dict[str, bool]:
            client = await get_redis()
            results = await asyncio.gather(
                *(client.exists(heartbeat_key(label)) for label in labels)
            )
            return {label: bool(exists) for label, exists in zip(labels, results, strict=True)}

        per_worker = await asyncio.wait_for(_run(), timeout=_PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        return False, dict.fromkeys(labels, False), "timeout"
    except Exception as exc:  # noqa: BLE001 — surface any driver/connection error
        return False, dict.fromkeys(labels, False), type(exc).__name__

    return all(per_worker.values()), per_worker, None


@router.get("/livez", tags=["Health"])
async def livez() -> dict[str, str]:
    """Liveness probe — process is up.

    Intentionally does not touch external services. Use ``/readyz`` for that.
    """
    return {"status": "ok"}


@router.get("/readyz", tags=["Health"])
async def readyz(request: Request, response: Response) -> dict[str, Any]:
    """Readiness probe — startup complete + Postgres + Redis reachable.

    Returns HTTP 503 when:

    * ``app.state.ready`` is ``False`` — the lifespan handler hasn't finished
      validating config and starting workers yet (or shutdown is in progress).
    * Either Postgres or Redis fails / times out (2s budget each).
    * Any expected worker is missing a fresh heartbeat key.

    Orchestrators (Railway, Kubernetes) use this to hold traffic on the
    previous container until the new one finishes booting and to drain a
    container before it stops accepting requests.
    """
    # Short-circuit before touching external services: if startup hasn't
    # completed (or shutdown has begun) the dependency probes are meaningless.
    startup_ready = bool(getattr(request.app.state, "ready", False))
    if not startup_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.info("readyz_not_ready", reason="startup_incomplete")
        return {
            "status": "starting",
            "checks": {"startup": {"ok": False, "error": "startup_incomplete"}},
        }

    postgres_result, redis_result, worker_result = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_worker_heartbeats(),
    )
    postgres_ok, postgres_err = postgres_result
    redis_ok, redis_err = redis_result
    workers_ok, worker_states, worker_err = worker_result

    checks = {
        "startup": {"ok": True, "error": None},
        "postgres": {"ok": postgres_ok, "error": postgres_err},
        "redis": {"ok": redis_ok, "error": redis_err},
        "workers": {
            "ok": workers_ok,
            "error": worker_err,
            "heartbeats": worker_states,
        },
    }

    if not (postgres_ok and redis_ok and workers_ok):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning(
            "readyz_failed",
            postgres_ok=postgres_ok,
            postgres_err=postgres_err,
            redis_ok=redis_ok,
            redis_err=redis_err,
            workers_ok=workers_ok,
            worker_err=worker_err,
            missing_heartbeats=[label for label, ok in worker_states.items() if not ok],
        )
        return {"status": "unavailable", "checks": checks}

    return {"status": "ok", "checks": checks}


@router.get("/version", tags=["Health"])
async def version() -> dict[str, str]:
    """Return the build's git SHA from ``RAILWAY_GIT_COMMIT_SHA``."""
    sha = os.getenv("RAILWAY_GIT_COMMIT_SHA", "unknown")
    return {"sha": sha}
