"""Deterministic disclosure and bounded client-state tests."""

import base64
import uuid

from app.services.telephony.inbound_call_policy import (
    DISCLOSURE_VERSION,
    build_inbound_disclosure,
    decode_inbound_disclosure_state,
    decode_inbound_terminal_state,
    encode_inbound_disclosure_state,
    encode_inbound_terminal_state,
)


def test_disclosure_copy_is_fixed_and_sanitizes_business_name() -> None:
    disclosure = build_inbound_disclosure("  Maxteriors\nLighting  ")

    assert disclosure == (
        "You are speaking with Maxteriors Lighting's AI assistant. "
        "This call will be transcribed to help with your request. "
        "By continuing, you agree to that processing."
    )
    assert DISCLOSURE_VERSION == "inbound-ai-transcription-v1"


def test_disclosure_state_round_trips_only_its_bound_message() -> None:
    message_id = uuid.uuid4()

    assert (
        decode_inbound_disclosure_state(encode_inbound_disclosure_state(message_id)) == message_id
    )
    assert decode_inbound_disclosure_state(encode_inbound_terminal_state("busy")) is None


def test_client_state_decoder_rejects_untrusted_or_noncanonical_values() -> None:
    uppercase_uuid = str(uuid.uuid4()).upper()
    noncanonical = base64.b64encode(
        f"inbound-disclosure:{DISCLOSURE_VERSION}:{uppercase_uuid}".encode()
    ).decode()

    assert decode_inbound_disclosure_state(noncanonical) is None
    assert decode_inbound_disclosure_state("x" * 257) is None
    assert decode_inbound_disclosure_state("not-base64") is None
    assert decode_inbound_disclosure_state(None) is None


def test_terminal_state_accepts_only_busy_or_unavailable() -> None:
    assert decode_inbound_terminal_state(encode_inbound_terminal_state("busy")) == "busy"
    assert (
        decode_inbound_terminal_state(encode_inbound_terminal_state("unavailable")) == "unavailable"
    )
    assert (
        decode_inbound_terminal_state(base64.b64encode(b"inbound-terminal:v1:other").decode())
        is None
    )
