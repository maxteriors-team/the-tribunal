"""Emergency inbound transfer behavior never exposes destinations and fails closed."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.core.config import settings
from app.services.telephony import inbound_fallback
from app.services.telephony.inbound_call_policy import decode_inbound_terminal_state

pytestmark = pytest.mark.asyncio


def _voice_service(*, transferred: bool = True, spoken: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        answer_call=AsyncMock(return_value=True),
        transfer_call=AsyncMock(return_value=transferred),
        speak_text=AsyncMock(return_value=spoken),
        hangup_call=AsyncMock(return_value=True),
        close=AsyncMock(),
    )


async def test_configured_fallback_transfers_without_logging_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voice = _voice_service()
    log = MagicMock()
    metric = MagicMock()
    monkeypatch.setattr(settings, "telnyx_api_key", "test-key")
    monkeypatch.setattr(inbound_fallback, "TelnyxVoiceService", MagicMock(return_value=voice))
    monkeypatch.setattr(inbound_fallback, "observe_inbound_fallback", metric)

    transferred = await inbound_fallback.transfer_inbound_to_fallback(
        call_control_id="provider-call-id",
        fallback_number="+12025550123",
        log=log,
        reason="provider_unavailable",
    )

    assert transferred is True
    voice.answer_call.assert_awaited_once_with("provider-call-id")
    voice.transfer_call.assert_awaited_once()
    assert "+12025550123" not in str(log.method_calls)
    assert metric.call_args_list == [call("attempted"), call("transferred")]


async def test_failed_transfer_plays_unavailable_notice_then_waits_to_hang_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transfer_voice = _voice_service(transferred=False)
    notice_voice = _voice_service(spoken=True)
    monkeypatch.setattr(settings, "telnyx_api_key", "test-key")
    monkeypatch.setattr(
        inbound_fallback,
        "TelnyxVoiceService",
        MagicMock(side_effect=(transfer_voice, notice_voice)),
    )
    monkeypatch.setattr(inbound_fallback, "observe_inbound_fallback", MagicMock())

    transferred = await inbound_fallback.route_inbound_to_fallback(
        call_control_id="provider-call-id",
        fallback_number="+12025550123",
        log=MagicMock(),
        reason="streaming_failed",
    )

    assert transferred is False
    notice_voice.speak_text.assert_awaited_once()
    client_state = notice_voice.speak_text.await_args.kwargs["client_state"]
    assert decode_inbound_terminal_state(client_state) == "unavailable"
    notice_voice.hangup_call.assert_not_awaited()


async def test_transfer_exception_routes_to_notice_without_logging_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transfer_voice = _voice_service()
    transfer_voice.transfer_call.side_effect = RuntimeError("provider-secret")
    notice_voice = _voice_service(spoken=True)
    log = MagicMock()
    monkeypatch.setattr(settings, "telnyx_api_key", "test-key")
    monkeypatch.setattr(
        inbound_fallback,
        "TelnyxVoiceService",
        MagicMock(side_effect=(transfer_voice, notice_voice)),
    )
    monkeypatch.setattr(inbound_fallback, "observe_inbound_fallback", MagicMock())

    transferred = await inbound_fallback.route_inbound_to_fallback(
        call_control_id="provider-call-id",
        fallback_number="+12025550123",
        log=log,
        reason="streaming_failed",
    )

    assert transferred is False
    notice_voice.speak_text.assert_awaited_once()
    assert "provider-secret" not in str(log.mock_calls)


async def test_notice_speech_failure_hangs_up_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    voice = _voice_service(spoken=False)
    monkeypatch.setattr(settings, "telnyx_api_key", "test-key")
    monkeypatch.setattr(inbound_fallback, "TelnyxVoiceService", MagicMock(return_value=voice))

    await inbound_fallback.end_inbound_call_with_notice(
        call_control_id="provider-call-id",
        notice="busy",
        log=MagicMock(),
        reason="caller_limit_reached",
    )

    voice.hangup_call.assert_awaited_once_with("provider-call-id")


async def test_lookup_failure_routes_to_unavailable_path(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenSession:
        async def __aenter__(self) -> object:
            raise RuntimeError("database unavailable")

        async def __aexit__(self, *_: object) -> None:
            return None

    route = AsyncMock(return_value=False)
    log = MagicMock()
    monkeypatch.setattr(inbound_fallback, "system_session", lambda _: _BrokenSession())
    monkeypatch.setattr(inbound_fallback, "route_inbound_to_fallback", route)

    await inbound_fallback.route_inbound_to_configured_fallback(
        call_control_id="provider-call-id",
        log=log,
        reason="bridge_failed",
    )

    route.assert_awaited_once_with(
        call_control_id="provider-call-id",
        fallback_number=None,
        log=log,
        reason="bridge_failed",
    )
    log.error.assert_called_once_with(
        "inbound_fallback_lookup_failed",
        reason="bridge_failed",
        error_type="RuntimeError",
    )
    assert "database unavailable" not in str(log.mock_calls)
