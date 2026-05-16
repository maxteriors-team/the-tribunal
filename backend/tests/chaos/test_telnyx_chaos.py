"""Chaos tests for the Telnyx SMS client.

These tests inject faults at the HTTP transport layer and assert that the
production retry policy (``app.services.telephony.telnyx._telnyx_retry``)
absorbs them per its contract:

- 5xx → retried up to 3 times total, surfaces on exhaustion.
- 4xx → terminal, raised immediately, never retried.
- Transport errors / timeouts → retried, surfaces on exhaustion.

We bypass ``send_message`` (which writes to the DB) and call
``_post_message`` directly, since the goal is to characterise the HTTP
boundary under chaos, not the persistence layer.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.telephony.telnyx import TelnyxSMSService
from tests.chaos.conftest import FaultStats, make_fault_transport


def _ok_response(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": {"id": "msg_ok", "to": [{"phone_number": "+15551234567"}]}},
    )


def _build_service_with_transport(transport: httpx.MockTransport) -> TelnyxSMSService:
    """Build a Telnyx service with the mock transport pre-wired.

    The service lazily constructs its ``httpx.AsyncClient`` in the ``client``
    property; we pre-seed ``_client`` so the transport is used instead.
    """
    svc = TelnyxSMSService(api_key="test-key")
    svc._client = httpx.AsyncClient(
        transport=transport,
        base_url=svc.BASE_URL,
        headers={
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
    )
    return svc


PAYLOAD: dict[str, str] = {
    "to": "+15551234567",
    "from": "+15557654321",
    "text": "hi",
    "type": "SMS",
}


@pytest.mark.asyncio
async def test_random_500s_are_retried_then_recovered(fault_stats: FaultStats) -> None:
    """A 100% 500-rate must eventually exhaust retries and raise.

    With ``_telnyx_retry`` configured for 3 attempts, the transport should
    see exactly 3 calls before HTTPStatusError surfaces.
    """
    transport, stats = make_fault_transport(
        ok_response=_ok_response,
        error_rate=1.0,
        seed=1,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await svc._post_message(PAYLOAD)

        assert exc_info.value.response.status_code == 500
        # 1 initial + 2 retries = 3.
        assert stats.total == 3
        assert stats.injected_500 == 3
        assert stats.delivered_ok == 0
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_partial_500s_recover_within_retry_budget(fault_stats: FaultStats) -> None:
    """A 50% 500-rate should usually recover within 3 attempts.

    Seeded RNG: with seed=2 the first call 500s, the second succeeds.
    """
    transport, stats = make_fault_transport(
        ok_response=_ok_response,
        error_rate=0.5,
        seed=2,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        result = await svc._post_message(PAYLOAD)
        assert result["data"]["id"] == "msg_ok"
        # Some 500s injected, but a success was eventually delivered.
        assert stats.delivered_ok == 1
        assert stats.total <= 3
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_timeouts_are_retried(fault_stats: FaultStats) -> None:
    """A 100% timeout-rate exhausts retries and surfaces ReadTimeout."""
    transport, stats = make_fault_transport(
        ok_response=_ok_response,
        timeout_rate=1.0,
        seed=3,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        with pytest.raises(httpx.ReadTimeout):
            await svc._post_message(PAYLOAD)
        assert stats.total == 3
        assert stats.injected_timeout == 3
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_latency_injection_does_not_change_outcome(fault_stats: FaultStats) -> None:
    """Adding 100-200ms per hop must not change request semantics.

    The test asserts the client still returns a 200 body — latency is a
    performance concern, not a correctness one. With the retry-sleep
    patched in the fixture, the test stays fast even if many hops fire.
    """
    transport, stats = make_fault_transport(
        ok_response=_ok_response,
        latency_ms_range=(100, 200),
        seed=4,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        result = await svc._post_message(PAYLOAD)
        assert result["data"]["id"] == "msg_ok"
        assert stats.delivered_ok == 1
        assert stats.injected_latency_ms >= 100
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_4xx_is_terminal_not_retried(fault_stats: FaultStats) -> None:
    """4xx responses must NOT trigger the retry path.

    Bad-request / auth failures are deterministic — re-issuing the call
    just burns rate limit. The transport should be hit exactly once.
    """

    def four_hundred(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errors": [{"detail": "bad number"}]})

    transport, stats = make_fault_transport(
        ok_response=four_hundred,
        seed=5,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await svc._post_message(PAYLOAD)
        assert exc_info.value.response.status_code == 400
        assert stats.total == 1
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_mixed_chaos_500_and_timeout(fault_stats: FaultStats) -> None:
    """Realistic mix: 30% 500s + 30% timeouts. Some calls fail, some pass.

    The contract under chaos is: never a silent corruption. Either the
    call raises a transport/5xx error, or it returns a real Telnyx body —
    no other outcomes.
    """
    transport, stats = make_fault_transport(
        ok_response=_ok_response,
        error_rate=0.3,
        timeout_rate=0.3,
        seed=6,
        stats=fault_stats,
    )
    svc = _build_service_with_transport(transport)
    try:
        outcomes: list[str] = []
        for _ in range(20):
            try:
                result = await svc._post_message(PAYLOAD)
                assert result["data"]["id"] == "msg_ok"
                outcomes.append("ok")
            except (httpx.HTTPStatusError, httpx.ReadTimeout):
                outcomes.append("failed")

        # Both outcomes must be observed — if every call passes or every
        # call fails, our RNG seed isn't actually exercising chaos.
        assert "ok" in outcomes, "no successful calls — chaos seed too harsh"
        assert "failed" in outcomes, "no failed calls — chaos seed too gentle"
    finally:
        await svc.close()
