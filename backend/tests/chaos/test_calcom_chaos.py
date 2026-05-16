"""Chaos tests for the Cal.com client.

Exercises ``CalComService._request_with_retry`` under transport-level
fault injection. The retry contract under test:

- 5xx → retried up to ``MAX_RETRIES`` (3) times, surfaces ``CalComError``
  on exhaustion.
- 401 → ``CalComAuthError`` immediately, no retry.
- 404 → ``CalComNotFoundError`` immediately, no retry.
- 429 → honors ``Retry-After``, retries.
- Network timeout → retried; surfaces ``CalComError`` on exhaustion.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.calendar.calcom import (
    CalComAuthError,
    CalComError,
    CalComNotFoundError,
    CalComService,
)
from tests.chaos.conftest import FaultStats, make_fault_transport


def _ok_booking(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": {"uid": "bk_ok", "id": 42}},
    )


def _build_service_with_transport(transport: httpx.MockTransport) -> CalComService:
    """Build a Cal.com service with the mock transport pre-wired."""
    svc = CalComService(api_key="test-key")
    svc._client = httpx.AsyncClient(
        transport=transport,
        headers={
            "Authorization": "Bearer test-key",
            "cal-api-version": "2024-08-13",
        },
    )
    return svc


@pytest.mark.asyncio
async def test_random_500s_exhaust_retries_then_raise(fault_stats: FaultStats) -> None:
    """100% 500-rate must surface ``CalComError`` after ``MAX_RETRIES`` hops."""
    transport, stats = make_fault_transport(
        ok_response=_ok_booking,
        error_rate=1.0,
        seed=11,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        client = await svc.get_client()
        with pytest.raises(CalComError):
            await svc._request_with_retry(
                "GET",
                "https://api.cal.com/v2/bookings/anything",
                client=client,
            )
        # MAX_RETRIES = 3 in app.services.calendar.calcom.
        assert stats.total == 3
        assert stats.injected_500 == 3
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_partial_500s_recover(fault_stats: FaultStats) -> None:
    """50% 500-rate should usually recover within MAX_RETRIES."""
    transport, stats = make_fault_transport(
        ok_response=_ok_booking,
        error_rate=0.5,
        seed=12,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        client = await svc.get_client()
        result = await svc._request_with_retry(
            "GET",
            "https://api.cal.com/v2/bookings/anything",
            client=client,
        )
        assert result["data"]["uid"] == "bk_ok"
        assert stats.delivered_ok == 1
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_timeouts_surface_calcom_error(fault_stats: FaultStats) -> None:
    """Persistent timeouts must wrap into ``CalComError``, never leak raw httpx."""
    transport, stats = make_fault_transport(
        ok_response=_ok_booking,
        timeout_rate=1.0,
        seed=13,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        client = await svc.get_client()
        with pytest.raises(CalComError):
            await svc._request_with_retry(
                "GET",
                "https://api.cal.com/v2/bookings/anything",
                client=client,
            )
        # Network errors should be retried up to MAX_RETRIES.
        assert stats.injected_timeout == 3
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_latency_injection_passes_through(fault_stats: FaultStats) -> None:
    """High latency must not change return value or raise an error."""
    transport, stats = make_fault_transport(
        ok_response=_ok_booking,
        latency_ms_range=(50, 150),
        seed=14,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        client = await svc.get_client()
        result = await svc._request_with_retry(
            "GET",
            "https://api.cal.com/v2/bookings/anything",
            client=client,
        )
        assert result["data"]["uid"] == "bk_ok"
        assert stats.injected_latency_ms >= 50
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_401_is_terminal_not_retried(fault_stats: FaultStats) -> None:
    """Auth failure should surface immediately as ``CalComAuthError``."""

    def four_oh_one(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    transport, stats = make_fault_transport(
        ok_response=four_oh_one,
        seed=15,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        client = await svc.get_client()
        with pytest.raises(CalComAuthError):
            await svc._request_with_retry(
                "GET",
                "https://api.cal.com/v2/bookings/anything",
                client=client,
            )
        assert stats.total == 1
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_404_is_terminal_not_retried(fault_stats: FaultStats) -> None:
    """Missing-resource should surface as ``CalComNotFoundError``, no retry."""

    def four_oh_four(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    transport, stats = make_fault_transport(
        ok_response=four_oh_four,
        seed=16,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        client = await svc.get_client()
        with pytest.raises(CalComNotFoundError):
            await svc._request_with_retry(
                "GET",
                "https://api.cal.com/v2/bookings/missing",
                client=client,
            )
        assert stats.total == 1
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_429_with_retry_after_is_retried(fault_stats: FaultStats) -> None:
    """A single 429 with a small Retry-After must retry and then succeed."""
    state = {"calls": 0}

    def maybe_429(_request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(
                429,
                json={"error": "rate limited"},
                headers={"Retry-After": "1"},
            )
        return _ok_booking(_request)

    transport, stats = make_fault_transport(
        ok_response=maybe_429,
        seed=17,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        client = await svc.get_client()
        result = await svc._request_with_retry(
            "GET",
            "https://api.cal.com/v2/bookings/anything",
            client=client,
        )
        assert result["data"]["uid"] == "bk_ok"
        # First call was 429, second succeeded — total 2 hops.
        assert state["calls"] == 2
        assert stats.total == 2
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_mixed_chaos_never_silent_corruption(fault_stats: FaultStats) -> None:
    """Under mixed faults every call either raises CalComError or returns a valid body."""
    transport, stats = make_fault_transport(
        ok_response=_ok_booking,
        error_rate=0.3,
        timeout_rate=0.2,
        latency_ms_range=(5, 25),
        seed=18,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        client = await svc.get_client()
        outcomes: list[str] = []
        for _ in range(15):
            try:
                result = await svc._request_with_retry(
                    "GET",
                    "https://api.cal.com/v2/bookings/anything",
                    client=client,
                )
                assert result == {"data": {"uid": "bk_ok", "id": 42}}
                outcomes.append("ok")
            except CalComError:
                outcomes.append("failed")

        # Sanity: chaos seed exercises both paths.
        assert "ok" in outcomes
        assert "failed" in outcomes
    finally:
        await svc.close()
