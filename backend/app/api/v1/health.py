"""Health, readiness, and version probes.

Three orthogonal endpoints follow the Kubernetes/Railway convention:

* ``/livez``  — liveness: the process is up and the event loop responsive. No
  external dependencies are checked. A 200 here only proves "I exist".
* ``/readyz`` — readiness: external dependencies (Postgres + Redis) reachable
  within a 2-second budget, plus the bundled product-help corpus present in
  this image. Returns 503 if a probe fails or times out, so load balancers
  drain the instance and an orchestrator refuses to promote the deploy.
* ``/version`` — the commit SHA of the running build, resolved by
  :func:`app.core.build_info.resolve_build_info` (falls back to ``"unknown"``).
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.core.build_info import resolve_build_info
from app.db.redis import get_redis
from app.db.session import AsyncSessionLocal
from app.services.knowledge.product_help import ProductHelpError, load_product_help_articles
from app.workers import WORKER_SPECS
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


def _check_product_help() -> tuple[bool, int, str | None]:
    """Verify the bundled product-help corpus shipped inside this image.

    The corpus is markdown read from disk, so a packaging mistake -- an ignore
    rule that drops ``docs/``, a build stage that forgets to copy it -- yields
    an image that builds, boots, and serves every endpoint normally while the
    in-app assistant answers "no matching help" to every product question.
    Nothing raises and nothing logs, so the only signal is a user eventually
    reporting that the assistant got worse.

    Results come from :func:`load_product_help_articles`' process-wide cache,
    so a passing check costs a cache hit rather than a directory walk per probe.
    """
    try:
        return True, len(load_product_help_articles()), None
    except ProductHelpError as exc:
        return False, 0, str(exc)
    except Exception as exc:  # noqa: BLE001 — surface any unexpected read error
        return False, 0, type(exc).__name__


def _expected_worker_labels() -> list[str]:
    """Return heartbeat labels of running workers that require health checks.

    A worker only counts toward the heartbeat check after its registry has
    produced a live instance — i.e. once :func:`start_all_workers` has
    completed. During cold start the registries are empty and this returns
    an empty list, so ``/readyz`` won't spuriously fail before workers boot.
    """
    labels: list[str] = []
    for spec in WORKER_SPECS:
        instance = spec.registry.get()
        if instance is None or not spec.health_metadata.heartbeat_required:
            continue
        labels.append(spec.health_metadata.component_name)
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
            keys = [heartbeat_key(label) for label in labels]
            # Single round-trip: ``MGET key1 key2 ...`` borrows at most one
            # connection from the shared Redis pool regardless of worker count,
            # returning values ordered identically to ``keys`` (``None`` for a
            # missing/expired key). A per-worker ``exists()`` fan-out via
            # ``asyncio.gather`` borrowed one connection each and exhausted the
            # bounded pool, raising ``MaxConnectionsError`` and reporting every
            # worker as down.
            values = await client.mget(keys)
            return {label: value is not None for label, value in zip(labels, values, strict=True)}

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
    """Readiness probe — startup complete + Postgres + Redis + help corpus.

    Returns HTTP 503 when:

    * ``app.state.ready`` is ``False`` — the lifespan handler hasn't finished
      validating config and starting workers yet (or shutdown is in progress).
    * Either Postgres or Redis fails / times out (2s budget each).
    * The bundled product-help corpus is missing from this image.

    The corpus gates readiness even though wedged workers (below) deliberately
    do not, because the two failures are not the same kind of thing. A worker
    heartbeat is dynamic and transient: it can recover on its own, and a
    restart actively makes it worse. The corpus is a static build artifact --
    it is either baked into the image or it is not, the answer never changes
    for the life of the process, and no restart can conjure the files. Failing
    readiness on it therefore cannot produce the restart loop documented below;
    what it does instead is stop an orchestrator from promoting a
    mis-packaged deploy, so the previous release keeps serving. That is the
    safe direction: a blocked deploy is visible in seconds, whereas the
    silent alternative is an assistant that has quietly stopped answering
    product questions in production and no failing check anywhere.

    Worker heartbeats are **reported but not gating**. This endpoint answers one
    question for the orchestrator: "can this container serve HTTP traffic?" A
    wedged nudge worker does not make the API unable to serve requests, but
    failing readiness on it made Railway restart the whole container — which
    cold-starts all ~28 workers at once, and ``start_all_workers`` runs each
    worker's first cycle immediately (jitter is only applied *after* the first
    sleep). That thundering herd re-exhausted the DB pool and wedged the
    heartbeats again, so the restart loop sustained the very outage it was
    reacting to. Every observed ``readyz_failed`` had ``postgres_ok=True`` and
    ``redis_ok=True`` — the API was healthy and being restarted anyway.

    Worker health is still surfaced in ``checks.workers`` here and, on its own,
    at ``/workers/health``, which alerting should page on instead.

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
    help_ok, help_articles, help_err = _check_product_help()

    checks = {
        "startup": {"ok": True, "error": None},
        "postgres": {"ok": postgres_ok, "error": postgres_err},
        "redis": {"ok": redis_ok, "error": redis_err},
        "product_help": {
            "ok": help_ok,
            "error": help_err,
            "articles": help_articles,
        },
        "workers": {
            "ok": workers_ok,
            "error": worker_err,
            "heartbeats": worker_states,
        },
    }

    missing_heartbeats = [label for label, ok in worker_states.items() if not ok]
    if not workers_ok:
        # Loud, but deliberately non-gating — see the docstring.
        logger.warning(
            "worker_heartbeats_degraded",
            worker_err=worker_err,
            missing_heartbeats=missing_heartbeats,
        )

    if not (postgres_ok and redis_ok and help_ok):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning(
            "readyz_failed",
            postgres_ok=postgres_ok,
            postgres_err=postgres_err,
            redis_ok=redis_ok,
            redis_err=redis_err,
            product_help_ok=help_ok,
            product_help_err=help_err,
            workers_ok=workers_ok,
            worker_err=worker_err,
            missing_heartbeats=missing_heartbeats,
        )
        return {"status": "unavailable", "checks": checks}

    if not workers_ok:
        return {"status": "degraded", "checks": checks}

    return {"status": "ok", "checks": checks}


@router.get("/workers/health", tags=["Health"])
async def workers_health(response: Response) -> dict[str, Any]:
    """Worker-heartbeat probe — the gating check ``/readyz`` deliberately isn't.

    Split out so alerting can page on wedged workers without an orchestrator
    treating them as a reason to restart (or refuse traffic to) the API.
    Returns 503 when any expected worker has no fresh heartbeat key.
    """
    workers_ok, worker_states, worker_err = await _check_worker_heartbeats()

    if not workers_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if workers_ok else "unavailable",
        "error": worker_err,
        "heartbeats": worker_states,
        "missing": [label for label, ok in worker_states.items() if not ok],
    }


@router.get("/version", tags=["Health"])
async def version() -> dict[str, str]:
    """Return the commit SHA of the running build.

    Resolved in order from ``RAILWAY_GIT_COMMIT_SHA`` (git-triggered Railway
    builds), ``BUILD_COMMIT_SHA`` (build arg), then the ``app/build_info.json``
    stamp that ``make deploy.backend`` bakes into ``railway up`` uploads,
    falling back to ``"unknown"``. ``source`` reports which one answered, so an
    ``"unknown"`` reading is diagnosable from the response alone.
    """
    info = resolve_build_info()
    return {"sha": info.sha, "source": info.source}
