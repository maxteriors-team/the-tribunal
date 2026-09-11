"""The recording notice authorises recording only for its own bound call."""

import base64
import uuid

from app.services.telephony.inbound_call_policy import encode_inbound_disclosure_state
from app.services.telephony.recording_notice import (
    RECORDING_NOTICE_TEXT,
    decode_recording_notice_state,
    encode_recording_notice_state,
)


def test_notice_copy_states_the_call_is_recorded() -> None:
    assert RECORDING_NOTICE_TEXT == "Just so you know, this call is recorded."


def test_notice_state_round_trips_only_its_bound_message() -> None:
    message_id = uuid.uuid4()
    other_id = uuid.uuid4()

    assert decode_recording_notice_state(encode_recording_notice_state(message_id)) == message_id
    assert decode_recording_notice_state(encode_recording_notice_state(other_id)) != message_id


def test_disclosure_state_never_authorises_recording() -> None:
    """A neighbouring feature's marker must not unlock the recorder."""
    assert decode_recording_notice_state(encode_inbound_disclosure_state(uuid.uuid4())) is None


def test_decoder_rejects_untrusted_or_noncanonical_values() -> None:
    uppercase_uuid = str(uuid.uuid4()).upper()
    noncanonical = base64.b64encode(f"recording-notice:v1:{uppercase_uuid}".encode()).decode()

    assert decode_recording_notice_state(noncanonical) is None
    assert decode_recording_notice_state(base64.b64encode(b"recording-notice:v1:").decode()) is None
    assert decode_recording_notice_state("x" * 257) is None
    assert decode_recording_notice_state("not-base64") is None
    assert decode_recording_notice_state(None) is None
    assert decode_recording_notice_state(b"bytes-not-str") is None
