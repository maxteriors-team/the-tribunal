"""Shared fault-injection primitives for chaos tests.

The helpers in this module wrap ``httpx.MockTransport`` so individual tests
can declare *what* should go wrong (random 500s, latency injection, timeouts)
without re-implementing the plumbing in every file.

All fault injectors are deterministic when given a seed, so flakes show up
as real regressions rather than RNG drift.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field

import httpx
import pytest

from app.core.circuit_breakers import ALL_BREAKERS

# Type alias for an MockTransport request handler.
Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]


@dataclass
class FaultStats:
    """Counters surfaced to tests after a run."""

    total: int = 0
    injected_500: int = 0
    injected_timeout: int = 0
    injected_latency_ms: int = 0
    delivered_ok: int = 0
    last_requests: list[httpx.Request] = field(default_factory=list)


def make_fault_transport(
    *,
    ok_response: Callable[[httpx.Request], httpx.Response],
    error_rate: float = 0.0,
    timeout_rate: float = 0.0,
    latency_ms_range: tuple[int, int] = (0, 0),
    seed: int = 0,
    stats: FaultStats | None = None,
) -> tuple[httpx.MockTransport, FaultStats]:
    """Build an ``httpx.MockTransport`` that injects faults.

    Args:
        ok_response: Builder for the successful response when no fault fires.
        error_rate: Probability in [0, 1] of returning a 500.
        timeout_rate: Probability in [0, 1] of raising ``httpx.ReadTimeout``.
            Evaluated *after* ``error_rate`` so the two are mutually exclusive.
        latency_ms_range: Sleep ``random.randint(lo, hi)`` ms before each
            response. Use (0, 0) to disable.
        seed: PRNG seed — deterministic per-test fault patterns.
        stats: Optional pre-allocated stats object to populate.

    Returns:
        ``(transport, stats)`` — pass ``transport`` to ``httpx.AsyncClient``
        and inspect ``stats`` after the run.
    """
    rng = random.Random(seed)
    s = stats if stats is not None else FaultStats()

    async def handler(request: httpx.Request) -> httpx.Response:
        s.total += 1
        s.last_requests.append(request)

        lo, hi = latency_ms_range
        if hi > 0:
            delay_ms = rng.randint(lo, hi)
            s.injected_latency_ms += delay_ms
            await asyncio.sleep(delay_ms / 1000.0)

        if rng.random() < error_rate:
            s.injected_500 += 1
            return httpx.Response(500, json={"error": "chaos-injected-500"})

        if rng.random() < timeout_rate:
            s.injected_timeout += 1
            raise httpx.ReadTimeout("chaos-injected-timeout", request=request)

        s.delivered_ok += 1
        return ok_response(request)

    return httpx.MockTransport(handler), s


@pytest.fixture
def fault_stats() -> FaultStats:
    """Fresh stats counter per test."""
    return FaultStats()


@pytest.fixture(autouse=True)
def _reset_circuit_breakers() -> Iterator[None]:
    """Close every breaker before each test so prior runs don't bleed state.

    pybreaker tracks failures across the process; without this reset a test
    that intentionally trips a breaker would poison later tests that share
    the same module-level singleton.
    """
    for cb in ALL_BREAKERS:
        cb.close()
    yield None
    for cb in ALL_BREAKERS:
        cb.close()


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry backoff sleep instantly.

    The shared provider HTTP client and any legacy tenacity-decorated
    methods sleep with real time. Real sleeps make the suite slow and time-
    dependent. We patch the specific call sites so latency *we* inject in
    the mock transport still applies — only the retry backoff is short-
    circuited.
    """
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.services.providers.http.asyncio.sleep",
        AsyncMock(return_value=None),
    )
    # Tenacity uses its own asyncio.sleep call site. Pin that too so any
    # remaining tenacity retry backoff doesn't add 1-10s per test.
    try:
        import tenacity.nap

        monkeypatch.setattr(tenacity.nap, "sleep", AsyncMock(return_value=None))
    except (ImportError, AttributeError):
        # Tenacity API drift: best-effort — retries still run, just slower.
        pass
