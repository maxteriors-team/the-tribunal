"""Tests for ``VoiceAgentBase._connect_with_backoff``.

The realtime/LLM provider legs (OpenAI Realtime ``self.ws`` and the hybrid
agent's Grok ``self.grok_ws``) establish their WebSocket through this helper so
a single dropped handshake is retried with exponential backoff instead of
failing the whole call. (The ElevenLabs TTS leg has its own mid-stream
``_reconnect`` loop — see ``test_elevenlabs_reconnect.py``.)

Pins the contract:

* Succeeds on the first attempt without sleeping.
* Retries transient failures and returns the connection once one succeeds.
* Exhausts after ``max_attempts`` and re-raises the last exception.
* Fails fast (no retry, no sleep) for ``non_retryable`` exceptions such as an
  auth rejection.
* Backoff grows exponentially: delay before retry N is
  ``base_delay * 2**N`` plus jitter in ``[0, base_delay)``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.ai import voice_agent_base as base_module
from app.services.ai.voice_agent import VoiceAgentSession


def _session() -> VoiceAgentSession:
    """A concrete agent instance; only ``self.logger`` is exercised here."""
    return VoiceAgentSession(api_key="k")


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture (and skip) backoff sleeps so tests stay instant."""
    captured: list[float] = []

    async def fake_sleep(delay: float) -> None:
        captured.append(delay)

    monkeypatch.setattr(base_module.asyncio, "sleep", fake_sleep)
    return captured


class TestConnectWithBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self, no_sleep: list[float]) -> None:
        conn = object()
        factory = AsyncMock(return_value=conn)

        result = await _session()._connect_with_backoff(factory)

        assert result is conn
        assert factory.await_count == 1
        assert no_sleep == []  # no backoff when the first attempt works

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self, no_sleep: list[float]) -> None:
        conn = object()
        factory = AsyncMock(
            side_effect=[OSError("blip 1"), OSError("blip 2"), conn],
        )

        result = await _session()._connect_with_backoff(factory, max_attempts=3)

        assert result is conn
        assert factory.await_count == 3
        assert len(no_sleep) == 2  # slept before each of the two retries

    @pytest.mark.asyncio
    async def test_exhausts_and_reraises_last_exception(self, no_sleep: list[float]) -> None:
        final = OSError("still down")
        factory = AsyncMock(side_effect=[OSError("down 1"), OSError("down 2"), final])

        with pytest.raises(OSError) as exc_info:
            await _session()._connect_with_backoff(factory, max_attempts=3)

        assert exc_info.value is final
        assert factory.await_count == 3
        # Two sleeps between three attempts; none after the final failure.
        assert len(no_sleep) == 2

    @pytest.mark.asyncio
    async def test_non_retryable_fails_fast(self, no_sleep: list[float]) -> None:
        class AuthRejectedError(Exception):
            pass

        factory = AsyncMock(side_effect=AuthRejectedError("bad credential"))

        with pytest.raises(AuthRejectedError):
            await _session()._connect_with_backoff(
                factory,
                max_attempts=5,
                non_retryable=(AuthRejectedError,),
            )

        assert factory.await_count == 1  # no retry on a doomed handshake
        assert no_sleep == []

    @pytest.mark.asyncio
    async def test_backoff_is_exponential(
        self,
        no_sleep: list[float],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pin jitter to 0 so the delays are deterministic powers of two.
        monkeypatch.setattr(base_module.random, "uniform", lambda _a, _b: 0.0)
        factory = AsyncMock(side_effect=RuntimeError("nope"))

        with pytest.raises(RuntimeError):
            await _session()._connect_with_backoff(
                factory,
                max_attempts=4,
                base_delay=0.5,
            )

        # base * 2**attempt for attempts 0..2 (the 4th attempt has no sleep).
        assert no_sleep == [0.5, 1.0, 2.0]

    @pytest.mark.asyncio
    async def test_jitter_stays_within_bounds(
        self,
        no_sleep: list[float],
    ) -> None:
        factory = AsyncMock(side_effect=RuntimeError("nope"))

        with pytest.raises(RuntimeError):
            await _session()._connect_with_backoff(
                factory,
                max_attempts=3,
                base_delay=0.5,
            )

        # Retry 0: [0.5, 1.0); retry 1: [1.0, 1.5).
        first, second = no_sleep
        assert 0.5 <= first < 1.0
        assert 1.0 <= second < 1.5
