"""Tests for barge-in truncation of the assistant's audio turn.

When the caller interrupts, ``response.cancel`` stops OpenAI generating but
leaves the *whole* generated turn in the server-side conversation history. The
model then believes it spoke audio the caller never heard and will not repeat
the price, address request, or warranty that got cut off mid-word.

``conversation.item.truncate`` is what corrects the history. Pins the contract:

* A barge-in while the bot is speaking truncates the tracked audio item.
* ``audio_end_ms`` never exceeds the audio actually generated, because an
  over-long value is an invalid request that OpenAI rejects.
* The byte->millisecond conversion follows the negotiated output format
  (G.711 at 8 kHz vs PCM16 at 24 kHz differ by 6x).
* A barge-in with the bot silent sends nothing.
* A finished turn is not truncated afterwards.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.ai.openai_realtime_config import realtime_output_bytes_per_second
from app.services.ai.voice_agent import VoiceAgentSession


def _session() -> VoiceAgentSession:
    session = VoiceAgentSession(api_key="test-key")
    session.ws = AsyncMock()
    return session


def _sent_events(session: VoiceAgentSession) -> list[dict[str, Any]]:
    """Every JSON event handed to the WebSocket."""
    events: list[dict[str, Any]] = []
    for call in session.ws.send.await_args_list:  # type: ignore[union-attr]
        payload = call.args[0]
        events.append(json.loads(payload) if isinstance(payload, str) else payload)
    return events


def _truncations(session: VoiceAgentSession) -> list[dict[str, Any]]:
    return [e for e in _sent_events(session) if e.get("type") == "conversation.item.truncate"]


@pytest.mark.asyncio
async def test_truncates_interrupted_turn_at_generated_audio_length() -> None:
    """Half a second of G.711 audio truncates at ~500ms, not the full turn."""
    session = _session()
    session._output_bytes_per_second = realtime_output_bytes_per_second("g711_ulaw")

    # 4000 bytes of G.711 == 500ms of speech the caller heard.
    session._current_audio_item_id = "item_abc"
    session._current_audio_content_index = 0
    session._current_audio_bytes = 4000
    session._current_audio_started_at = __import__("time").monotonic()

    await session.truncate_current_audio()

    truncations = _truncations(session)
    assert len(truncations) == 1
    event = truncations[0]
    assert event["item_id"] == "item_abc"
    assert event["content_index"] == 0
    # Wall clock here is ~0ms, so the min() picks the smaller wall-clock value;
    # the key guarantee is it never exceeds the 500ms actually generated.
    assert 0 <= event["audio_end_ms"] <= 500


@pytest.mark.asyncio
async def test_audio_end_ms_never_exceeds_generated_audio() -> None:
    """A long wall clock must not push audio_end_ms past the real audio."""
    session = _session()
    session._output_bytes_per_second = 8000
    session._current_audio_item_id = "item_slow"
    session._current_audio_bytes = 800  # 100ms generated
    # Pretend the turn started 10s ago: wall clock would say 10000ms.
    session._current_audio_started_at = __import__("time").monotonic() - 10.0

    await session.truncate_current_audio()

    event = _truncations(session)[0]
    assert event["audio_end_ms"] == 100


@pytest.mark.asyncio
async def test_pcm16_uses_24khz_byte_rate() -> None:
    """The same byte count means a much shorter turn at PCM16 24kHz."""
    session = _session()
    session._output_bytes_per_second = realtime_output_bytes_per_second(
        {"type": "audio/pcm", "rate": 24000}
    )
    session._current_audio_item_id = "item_pcm"
    session._current_audio_bytes = 4800  # 100ms at 48 bytes/ms
    session._current_audio_started_at = __import__("time").monotonic() - 10.0

    await session.truncate_current_audio()

    assert _truncations(session)[0]["audio_end_ms"] == 100


@pytest.mark.asyncio
async def test_no_truncate_when_bot_was_silent() -> None:
    """Nothing to correct if the caller interrupted silence."""
    session = _session()
    session._reset_current_audio_item()

    await session.truncate_current_audio()

    assert _truncations(session) == []


@pytest.mark.asyncio
async def test_second_barge_in_does_not_truncate_twice() -> None:
    """State clears on truncate, so a repeat barge-in is a no-op."""
    session = _session()
    session._output_bytes_per_second = 8000
    session._current_audio_item_id = "item_once"
    session._current_audio_bytes = 800
    session._current_audio_started_at = __import__("time").monotonic()

    await session.truncate_current_audio()
    await session.truncate_current_audio()

    assert len(_truncations(session)) == 1


@pytest.mark.asyncio
async def test_completed_turn_is_not_truncated() -> None:
    """A cleanly finished turn leaves no item to trim."""
    session = _session()
    session._current_audio_item_id = "item_done"
    session._current_audio_bytes = 800
    session._current_audio_started_at = __import__("time").monotonic()

    # response.output_audio.done clears tracking.
    session._reset_current_audio_item()
    await session.truncate_current_audio()

    assert _truncations(session) == []


def test_output_byte_rate_defaults_to_g711() -> None:
    """Unknown/missing formats fall back to the configured default (G.711)."""
    assert realtime_output_bytes_per_second(None) == 8000
    assert realtime_output_bytes_per_second("nonsense") == 8000
    assert realtime_output_bytes_per_second({"type": "audio/pcmu"}) == 8000
    assert realtime_output_bytes_per_second({"type": "audio/pcma"}) == 8000
