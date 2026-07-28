"""Tests for the Telnyx media-stream ticket.

These cover the authorization boundary for ``/voice/stream/{call_id}``, which
carries live customer call audio. The call control ID in that path is not a
secret, so the ticket is the only thing preventing an unauthenticated peer from
joining a live call.
"""

import time

import pytest

from app.services.telephony.stream_auth import (
    STREAM_TOKEN_PARAM,
    mint_stream_token,
    verify_stream_token,
)
from app.services.telephony.telnyx_voice import TelnyxVoiceService

CALL_ID = "v3:abc123-call-control-id"


def test_minted_token_verifies_for_its_own_call_id() -> None:
    assert verify_stream_token(CALL_ID, mint_stream_token(CALL_ID)) is True


def test_token_is_bound_to_a_single_call_id() -> None:
    """A ticket for one call must not authorize another call's stream."""
    token = mint_stream_token(CALL_ID)
    assert verify_stream_token("v3:some-other-call", token) is False


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "not-a-token",
        "123456",  # no separator
        ".",  # empty halves
        "abc.def",  # non-numeric expiry
        f"{int(time.time()) + 300}.",  # missing signature
        f"{int(time.time()) + 300}.deadbeef",  # wrong signature
    ],
)
def test_malformed_tokens_fail_closed(token: str | None) -> None:
    assert verify_stream_token(CALL_ID, token) is False


def test_expired_token_is_rejected() -> None:
    assert verify_stream_token(CALL_ID, mint_stream_token(CALL_ID, ttl_seconds=-1)) is False


def test_signature_alone_cannot_be_replayed_with_a_later_expiry() -> None:
    """The expiry is inside the signed payload, so it cannot be extended."""
    token = mint_stream_token(CALL_ID, ttl_seconds=1)
    _, _, signature = token.partition(".")
    forged = f"{int(time.time()) + 86400}.{signature}"
    assert verify_stream_token(CALL_ID, forged) is False


def test_empty_call_id_is_rejected() -> None:
    assert verify_stream_token("", mint_stream_token("")) is False


def test_build_stream_url_embeds_a_verifiable_ticket() -> None:
    url = TelnyxVoiceService.build_stream_url(CALL_ID, "https://api.example.com")

    assert url.startswith(f"wss://api.example.com/voice/stream/{CALL_ID}?")
    assert f"{STREAM_TOKEN_PARAM}=" in url

    token = url.split(f"{STREAM_TOKEN_PARAM}=", 1)[1].split("&", 1)[0]
    assert verify_stream_token(CALL_ID, token) is True


def test_build_stream_url_keeps_outbound_flag_alongside_the_ticket() -> None:
    url = TelnyxVoiceService.build_stream_url(
        CALL_ID, "https://api.example.com", is_outbound=True
    )

    assert "is_outbound=true" in url
    token = url.split(f"{STREAM_TOKEN_PARAM}=", 1)[1].split("&", 1)[0]
    assert verify_stream_token(CALL_ID, token) is True
