"""Tests for ``app.api.webhooks.telnyx_call_handlers``.

Pins the call-lifecycle handler contracts:

- ``handle_call_initiated`` — creates a ringing Message + Conversation
  row, fires the incoming-call push, attempts auto-answer. Idempotent
  on ``call_control_id`` (Telnyx retries on 5xx / timeout).
- ``handle_call_answered`` — transitions a Message to ``answered`` and
  (for outbound calls with an assigned agent) starts the audio stream.
- ``handle_call_hangup`` — classifies the call outcome from
  ``hangup_cause`` / ``duration_seconds`` / ``hangup_source``, captures
  recording URL, and updates campaign stats / engagement *exactly once*
  per call (subsequent hangup retries short-circuit the counters).
- ``handle_machine_detection`` — hangs up the call and triggers SMS
  fallback when Telnyx reports voicemail/fax.

Real-shape fixtures are loaded from ``tests/fixtures/webhooks/telnyx/``.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.webhooks import telnyx_call_handlers as handlers
from app.core.config import settings as app_settings
from app.models.conversation import MessageStatus
from tests.fixtures.webhooks import load_telnyx_payload

# --------------------------------------------------------------------------- #
# Shared mock plumbing
# --------------------------------------------------------------------------- #


class _Scalars:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def first(self) -> Any:
        return self._scalar


class _Result:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._scalar)


def _make_db(execute_returns: list[Any]) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(execute_returns))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.get = AsyncMock(return_value=None)
    return db


def _patch_session_local(monkeypatch: pytest.MonkeyPatch, db: MagicMock) -> None:
    class _CM:
        async def __aenter__(self) -> MagicMock:  # noqa: N805
            return db

        async def __aexit__(self, *exc: Any) -> None:  # noqa: N805
            return None

    monkeypatch.setattr(handlers, "AsyncSessionLocal", lambda: _CM())


def _make_log() -> MagicMock:
    log = MagicMock()
    log.bind = MagicMock(return_value=log)
    return log


@pytest.fixture(autouse=True)
def _stub_metrics_and_push(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Silence Prometheus counters + push notifications globally."""
    from app.services.telephony.inbound_screening import ScreeningOutcome, SpamDecision

    stubs: dict[str, MagicMock] = {}

    monkeypatch.setattr(
        handlers,
        "observe_voice_call_started",
        MagicMock(return_value=None),
    )

    # Default: screening allows the call and no routing reason is inferred, so
    # handle_call_initiated never issues extra DB queries unless a test opts in.
    screener = MagicMock()
    screener.screen = AsyncMock(
        return_value=ScreeningOutcome(decision=SpamDecision.ALLOW, reason=None)
    )
    monkeypatch.setattr(handlers, "_inbound_screener", screener)
    stubs["screener"] = screener

    classify = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "classify_inbound_reason", classify)
    stubs["classify_inbound_reason"] = classify

    reject = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "_reject_inbound_call", reject)
    stubs["reject"] = reject

    take_voicemail = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "take_inbound_voicemail", take_voicemail)
    stubs["take_inbound_voicemail"] = take_voicemail
    monkeypatch.setattr(
        handlers,
        "observe_voice_call_completed",
        MagicMock(return_value=None),
    )

    push = MagicMock()
    push.send_to_workspace_members = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "push_notification_service", push)
    stubs["push"] = push

    # Disable auto-answer side effects unless a test re-enables them.
    auto_answer = AsyncMock(return_value=None)
    monkeypatch.setattr(
        handlers,
        "auto_answer_call_if_agent_assigned",
        auto_answer,
    )
    stubs["auto_answer"] = auto_answer

    return stubs


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def call_initiated() -> dict[str, Any]:
    return load_telnyx_payload("call_initiated.json")


@pytest.fixture
def call_answered() -> dict[str, Any]:
    return load_telnyx_payload("call_answered.json")


@pytest.fixture
def hangup_normal() -> dict[str, Any]:
    return load_telnyx_payload("call_hangup_normal.json")


@pytest.fixture
def hangup_rejected() -> dict[str, Any]:
    return load_telnyx_payload("call_hangup_rejected.json")


@pytest.fixture
def hangup_no_answer() -> dict[str, Any]:
    return load_telnyx_payload("call_hangup_no_answer.json")


@pytest.fixture
def hangup_with_recording() -> dict[str, Any]:
    return load_telnyx_payload("call_hangup_with_recording.json")


@pytest.fixture
def machine_detection() -> dict[str, Any]:
    return load_telnyx_payload("call_machine_detection.json")


# --------------------------------------------------------------------------- #
# handle_call_initiated
# --------------------------------------------------------------------------- #


async def test_call_initiated_returns_when_required_fields_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _make_log()

    await handlers.handle_call_initiated({}, log)

    log.warning.assert_any_call("missing_required_fields")


async def test_call_initiated_returns_when_phone_number_unknown(
    monkeypatch: pytest.MonkeyPatch,
    call_initiated: dict[str, Any],
) -> None:
    """Inbound call to a number we don't own → log + return, no DB writes."""
    db = _make_db(execute_returns=[_Result(scalar=None)])  # PhoneNumber miss
    _patch_session_local(monkeypatch, db)
    log = _make_log()

    await handlers.handle_call_initiated(call_initiated, log)

    log.warning.assert_any_call(
        "phone_number_not_found",
        to_number="+12125550100",
    )
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_call_initiated_creates_message_and_conversation(
    monkeypatch: pytest.MonkeyPatch,
    call_initiated: dict[str, Any],
    _stub_metrics_and_push: dict[str, MagicMock],
) -> None:
    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id
    phone_record.phone_number = "+12125550100"
    phone_record.assigned_agent_id = None

    # Execute order in handle_call_initiated when conversation/contact absent:
    #   1. PhoneNumber lookup
    #   2. Message dedupe (returns None → fresh)
    #   3. Conversation lookup (returns None → create new)
    #   4. Contact lookup (returns None → no contact link)
    db = _make_db(
        execute_returns=[
            _Result(scalar=phone_record),
            _Result(scalar=None),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    db.refresh = AsyncMock()
    _patch_session_local(monkeypatch, db)

    await handlers.handle_call_initiated(call_initiated, _make_log())

    # Conversation + Message both added.
    added_types = [type(c.args[0]).__name__ for c in db.add.call_args_list]
    assert "Conversation" in added_types
    assert "Message" in added_types
    db.commit.assert_awaited()
    _stub_metrics_and_push["push"].send_to_workspace_members.assert_awaited_once()
    _stub_metrics_and_push["auto_answer"].assert_awaited_once()


async def test_call_initiated_links_known_caller_by_phone_hash(
    monkeypatch: pytest.MonkeyPatch,
    call_initiated: dict[str, Any],
    _stub_metrics_and_push: dict[str, MagicMock],
) -> None:
    # Regression: the contact lookup must match the caller by deterministic
    # phone_hash, not the Fernet-encrypted phone_number column (which never
    # matches an equality compare), so a known caller's conversation is linked
    # to their existing contact instead of looking like a brand-new lead.
    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id
    phone_record.phone_number = "+12125550100"
    phone_record.assigned_agent_id = None

    known_contact = MagicMock()
    known_contact.id = 4321

    db = _make_db(
        execute_returns=[
            _Result(scalar=phone_record),  # PhoneNumber lookup
            _Result(scalar=None),  # Message dedupe → fresh
            _Result(scalar=None),  # Conversation lookup → create new
            _Result(scalar=known_contact),  # Contact lookup by phone_hash → match
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_call_initiated(call_initiated, _make_log())

    conversations = [
        c.args[0] for c in db.add.call_args_list if type(c.args[0]).__name__ == "Conversation"
    ]
    assert conversations, "expected a Conversation to be created"
    assert conversations[0].contact_id == known_contact.id


async def test_call_initiated_is_idempotent_on_retry(
    monkeypatch: pytest.MonkeyPatch,
    call_initiated: dict[str, Any],
    _stub_metrics_and_push: dict[str, MagicMock],
) -> None:
    """Telnyx retry with the same ``call_control_id`` must NOT create a
    second ringing Message or re-fire the push / auto-answer.
    """
    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id

    # Message dedupe SELECT hits → bail out.
    db = _make_db(
        execute_returns=[
            _Result(scalar=phone_record),
            _Result(scalar=uuid.uuid4()),  # existing Message.id
        ]
    )
    _patch_session_local(monkeypatch, db)

    log = _make_log()
    await handlers.handle_call_initiated(call_initiated, log)

    log.info.assert_any_call(
        "call_initiated_duplicate_skipped",
        call_control_id="v3:call-control-id-initiated-001",
    )
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    _stub_metrics_and_push["push"].send_to_workspace_members.assert_not_awaited()
    _stub_metrics_and_push["auto_answer"].assert_not_awaited()


def _added_message(db: MagicMock) -> Any:
    """Return the Message instance passed to ``db.add`` (or None)."""
    for call in db.add.call_args_list:
        obj = call.args[0]
        if type(obj).__name__ == "Message":
            return obj
    return None


async def test_call_initiated_rejects_spam_caller(
    monkeypatch: pytest.MonkeyPatch,
    call_initiated: dict[str, Any],
    _stub_metrics_and_push: dict[str, MagicMock],
) -> None:
    """A caller screened as REJECT is hung up before answering: no push, no
    auto-answer, and the decision is persisted on the call Message."""
    from app.services.telephony.inbound_screening import ScreeningOutcome, SpamDecision

    _stub_metrics_and_push["screener"].screen = AsyncMock(
        return_value=ScreeningOutcome(decision=SpamDecision.REJECT, reason="global_opt_out")
    )

    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id
    phone_record.phone_number = "+12125550100"
    phone_record.assigned_agent_id = None

    db = _make_db(
        execute_returns=[
            _Result(scalar=phone_record),
            _Result(scalar=None),  # message dedupe
            _Result(scalar=None),  # conversation lookup
            _Result(scalar=None),  # contact lookup
        ]
    )
    _patch_session_local(monkeypatch, db)

    log = _make_log()
    await handlers.handle_call_initiated(call_initiated, log)

    message = _added_message(db)
    assert message is not None
    assert message.screening_decision == "reject"
    assert message.screening_reason == "global_opt_out"

    _stub_metrics_and_push["reject"].assert_awaited_once()
    _stub_metrics_and_push["auto_answer"].assert_not_awaited()
    _stub_metrics_and_push["push"].send_to_workspace_members.assert_not_awaited()
    log.info.assert_any_call(
        "inbound_call_rejected_spam",
        screening_reason="global_opt_out",
        call_control_id="v3:call-control-id-initiated-001",
    )


async def test_call_initiated_challenge_routes_to_voicemail(
    monkeypatch: pytest.MonkeyPatch,
    call_initiated: dict[str, Any],
    _stub_metrics_and_push: dict[str, MagicMock],
) -> None:
    """A CHALLENGE outcome answers to voicemail instead of the AI agent."""
    from app.services.telephony.inbound_screening import ScreeningOutcome, SpamDecision

    _stub_metrics_and_push["screener"].screen = AsyncMock(
        return_value=ScreeningOutcome(decision=SpamDecision.CHALLENGE, reason="reputation_suspect")
    )

    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id
    phone_record.phone_number = "+12125550100"
    phone_record.assigned_agent_id = None

    db = _make_db(
        execute_returns=[
            _Result(scalar=phone_record),
            _Result(scalar=None),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_call_initiated(call_initiated, _make_log())

    message = _added_message(db)
    assert message.screening_decision == "challenge"
    # Voicemail challenge runs; the AI auto-answer path does not.
    _stub_metrics_and_push["take_inbound_voicemail"].assert_awaited_once()
    _stub_metrics_and_push["auto_answer"].assert_not_awaited()
    # Operators are still notified of the (challenged) incoming call.
    _stub_metrics_and_push["push"].send_to_workspace_members.assert_awaited_once()


async def test_call_initiated_passes_routing_reason_to_auto_answer(
    monkeypatch: pytest.MonkeyPatch,
    call_initiated: dict[str, Any],
    _stub_metrics_and_push: dict[str, MagicMock],
) -> None:
    """A classified caller reason is persisted and forwarded to auto-answer for
    reason-based agent routing."""
    _stub_metrics_and_push["classify_inbound_reason"] = AsyncMock(return_value="billing")
    monkeypatch.setattr(
        handlers, "classify_inbound_reason", _stub_metrics_and_push["classify_inbound_reason"]
    )

    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id
    phone_record.phone_number = "+12125550100"
    phone_record.assigned_agent_id = None

    db = _make_db(
        execute_returns=[
            _Result(scalar=phone_record),
            _Result(scalar=None),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_call_initiated(call_initiated, _make_log())

    message = _added_message(db)
    assert message.routing_reason == "billing"
    _stub_metrics_and_push["auto_answer"].assert_awaited_once()
    assert _stub_metrics_and_push["auto_answer"].await_args.kwargs["reason"] == "billing"


# --------------------------------------------------------------------------- #
# handle_call_answered
# --------------------------------------------------------------------------- #


async def test_call_answered_returns_when_message_missing(
    monkeypatch: pytest.MonkeyPatch,
    call_answered: dict[str, Any],
) -> None:
    db = _make_db(execute_returns=[_Result(scalar=None)])
    _patch_session_local(monkeypatch, db)
    log = _make_log()

    await handlers.handle_call_answered(call_answered, log)

    log.error.assert_any_call(
        "message_not_found_for_call",
        call_control_id="v3:call-control-id-initiated-001",
    )
    db.commit.assert_not_awaited()


async def test_call_answered_inbound_just_transitions_status(
    monkeypatch: pytest.MonkeyPatch,
    call_answered: dict[str, Any],
) -> None:
    """Inbound calls don't start outbound audio streaming — status only."""
    message = MagicMock()
    message.id = uuid.uuid4()
    message.direction = "inbound"
    message.agent_id = None
    message.status = MessageStatus.RINGING
    message.conversation = MagicMock()
    message.conversation.assigned_agent_id = None

    db = _make_db(execute_returns=[_Result(scalar=message)])
    _patch_session_local(monkeypatch, db)

    await handlers.handle_call_answered(call_answered, _make_log())

    assert message.status == MessageStatus.ANSWERED
    db.commit.assert_awaited()


async def test_call_answered_outbound_with_agent_starts_streaming(
    monkeypatch: pytest.MonkeyPatch,
    call_answered: dict[str, Any],
) -> None:
    """Outbound call answered + agent assigned → audio stream is initiated."""
    agent_id = uuid.uuid4()
    message = MagicMock()
    message.id = uuid.uuid4()
    message.conversation_id = uuid.uuid4()
    message.direction = "outbound"
    message.agent_id = agent_id
    message.conversation = MagicMock()
    message.conversation.assigned_agent_id = agent_id

    agent = MagicMock()
    agent.id = agent_id
    agent.is_active = True
    agent.enable_recording = True

    db = _make_db(
        execute_returns=[
            _Result(scalar=message),  # initial Message lookup
            _Result(scalar=agent),  # Agent lookup
        ]
    )
    _patch_session_local(monkeypatch, db)

    # Provide a fake Telnyx API key so streaming path runs.
    monkeypatch.setattr(app_settings, "telnyx_api_key", "test-key")
    monkeypatch.setattr(
        app_settings,
        "api_base_url",
        "https://api.example.com",
    )

    voice_service = MagicMock()
    voice_service.start_audio_streaming = AsyncMock(return_value=True)
    voice_service.start_recording = AsyncMock(return_value=True)
    voice_service.close = AsyncMock(return_value=None)

    # The handler imports TelnyxVoiceService inside the function; patch it on
    # the source module before the handler imports it.
    from app.services.telephony import telnyx_voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "TelnyxVoiceService",
        lambda *a, **kw: voice_service,
    )

    await handlers.handle_call_answered(call_answered, _make_log())

    voice_service.start_audio_streaming.assert_awaited_once()
    voice_service.start_recording.assert_awaited_once()
    voice_service.close.assert_awaited()


# --------------------------------------------------------------------------- #
# handle_call_hangup
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _stub_hangup_side_effects(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Stub helpers imported lazily inside ``handle_call_hangup``."""
    stubs: dict[str, MagicMock] = {}

    from app.services.ai import call_outcome_service
    from app.services.campaigns import campaign_call_stats, sms_fallback
    from app.services.contacts import engagement_score

    create_outcome = AsyncMock(return_value=None)
    monkeypatch.setattr(
        call_outcome_service,
        "create_outcome_from_hangup",
        create_outcome,
    )
    stubs["create_outcome_from_hangup"] = create_outcome

    update_stats = AsyncMock(return_value=None)
    monkeypatch.setattr(
        campaign_call_stats,
        "update_campaign_call_stats",
        update_stats,
    )
    stubs["update_campaign_call_stats"] = update_stats

    trigger_fallback = AsyncMock(return_value=None)
    monkeypatch.setattr(
        sms_fallback,
        "trigger_sms_fallback_for_call",
        trigger_fallback,
    )
    stubs["trigger_sms_fallback_for_call"] = trigger_fallback

    record_engagement = AsyncMock(return_value=None)
    monkeypatch.setattr(engagement_score, "record_engagement", record_engagement)
    stubs["record_engagement"] = record_engagement

    return stubs


def _make_hangup_message(
    *,
    direction: str = "outbound",
    status: Any = MessageStatus.ANSWERED,
    booking_outcome: str | None = None,
    duration_seconds: int = 0,
) -> MagicMock:
    message = MagicMock()
    message.id = uuid.uuid4()
    message.conversation_id = uuid.uuid4()
    message.direction = direction
    message.status = status
    message.booking_outcome = booking_outcome
    message.duration_seconds = duration_seconds
    message.error_code = None
    message.error_message = None
    message.recording_url = None
    message.agent_id = uuid.uuid4()
    message.conversation = MagicMock()
    message.conversation.workspace_id = uuid.uuid4()
    message.conversation.contact_id = 123
    return message


async def test_call_hangup_message_missing_no_op(
    monkeypatch: pytest.MonkeyPatch,
    hangup_normal: dict[str, Any],
    _stub_hangup_side_effects: dict[str, MagicMock],
) -> None:
    db = _make_db(execute_returns=[_Result(scalar=None)])
    _patch_session_local(monkeypatch, db)

    await handlers.handle_call_hangup(hangup_normal, _make_log())

    db.commit.assert_not_awaited()
    _stub_hangup_side_effects["update_campaign_call_stats"].assert_not_awaited()


async def test_call_hangup_normal_clearing_85s_completes(
    monkeypatch: pytest.MonkeyPatch,
    hangup_normal: dict[str, Any],
    _stub_hangup_side_effects: dict[str, MagicMock],
) -> None:
    """85s NORMAL_CLEARING is a real conversation → completed."""
    message = _make_hangup_message()

    # Hangup execute order with no reconciliation hits:
    #   1. Message lookup
    #   2. _reconcile_booking_outcome: Appointment-by-message_id
    #   3. _reconcile_booking_outcome: Appointment-by-fuzzy match
    db = _make_db(
        execute_returns=[
            _Result(scalar=message),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_call_hangup(hangup_normal, _make_log())

    assert message.status == MessageStatus.COMPLETED
    assert message.duration_seconds == 85
    _stub_hangup_side_effects["update_campaign_call_stats"].assert_awaited_once()
    # No SMS fallback for completed calls (classification.outcome is None).
    _stub_hangup_side_effects["trigger_sms_fallback_for_call"].assert_not_awaited()


async def test_call_hangup_rejected_marks_failed_and_triggers_fallback(
    monkeypatch: pytest.MonkeyPatch,
    hangup_rejected: dict[str, Any],
    _stub_hangup_side_effects: dict[str, MagicMock],
) -> None:
    message = _make_hangup_message()

    db = _make_db(
        execute_returns=[
            _Result(scalar=message),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    _patch_session_local(monkeypatch, db)

    log = _make_log()
    await handlers.handle_call_hangup(hangup_rejected, log)

    assert message.status == MessageStatus.FAILED
    assert message.error_code == "CALL_REJECTED"
    log.info.assert_any_call("rejected_call_detected", hangup_source="callee")
    _stub_hangup_side_effects["trigger_sms_fallback_for_call"].assert_awaited_once()


async def test_call_hangup_no_answer_marks_failed_and_triggers_fallback(
    monkeypatch: pytest.MonkeyPatch,
    hangup_no_answer: dict[str, Any],
    _stub_hangup_side_effects: dict[str, MagicMock],
) -> None:
    message = _make_hangup_message()

    db = _make_db(
        execute_returns=[
            _Result(scalar=message),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_call_hangup(hangup_no_answer, _make_log())

    assert message.status == MessageStatus.FAILED
    assert message.error_code == "NO_ANSWER"
    _stub_hangup_side_effects["trigger_sms_fallback_for_call"].assert_awaited_once()


async def test_call_hangup_captures_recording_url(
    monkeypatch: pytest.MonkeyPatch,
    hangup_with_recording: dict[str, Any],
    _stub_hangup_side_effects: dict[str, MagicMock],
) -> None:
    message = _make_hangup_message()

    db = _make_db(
        execute_returns=[
            _Result(scalar=message),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_call_hangup(hangup_with_recording, _make_log())

    assert message.recording_url == "https://recordings.telnyx.example/rec-id-001.mp3"
    assert message.status == MessageStatus.COMPLETED


async def test_call_hangup_retry_skips_engagement_and_campaign_stats(
    monkeypatch: pytest.MonkeyPatch,
    hangup_normal: dict[str, Any],
    _stub_hangup_side_effects: dict[str, MagicMock],
) -> None:
    """Telnyx retried hangup (Message already in terminal state) must not
    double-count engagement, campaign stats, or completion metrics.

    The handler keys this off the captured ``prior_status`` so the
    classifier still runs (status is recomputed) but counters do not.
    """
    message = _make_hangup_message(status=MessageStatus.COMPLETED)

    db = _make_db(
        execute_returns=[
            _Result(scalar=message),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    _patch_session_local(monkeypatch, db)

    log = _make_log()
    await handlers.handle_call_hangup(hangup_normal, log)

    log.info.assert_any_call(
        "hangup_retry_detected",
        message_id=str(message.id),
        prior_status=MessageStatus.COMPLETED,
    )
    _stub_hangup_side_effects["update_campaign_call_stats"].assert_not_awaited()
    _stub_hangup_side_effects["record_engagement"].assert_not_awaited()


async def test_call_hangup_successful_booking_overrides_failed_status(
    monkeypatch: pytest.MonkeyPatch,
    hangup_no_answer: dict[str, Any],
    _stub_hangup_side_effects: dict[str, MagicMock],
) -> None:
    """Booking success on a NO_ANSWER cause must promote status to completed.

    Edge case: the agent booked the appointment via tool call but the
    underlying call leg terminated with NO_ANSWER. The classifier marks
    that FAILED; the override restores COMPLETED.
    """
    message = _make_hangup_message(booking_outcome="success")

    db = _make_db(
        execute_returns=[
            _Result(scalar=message),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_call_hangup(hangup_no_answer, _make_log())

    assert message.status == MessageStatus.COMPLETED


# --------------------------------------------------------------------------- #
# handle_machine_detection
# --------------------------------------------------------------------------- #


async def test_machine_detection_human_is_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``human`` detection result must NOT hang up or send fallback."""
    payload = {"call_control_id": "x", "result": "human"}

    await handlers.handle_machine_detection(payload, _make_log())
    # If we got here without exceptions and no DB session was opened, success.


async def test_machine_detection_machine_hangs_up_and_triggers_fallback(
    monkeypatch: pytest.MonkeyPatch,
    machine_detection: dict[str, Any],
) -> None:
    message = MagicMock()
    message.id = uuid.uuid4()
    message.conversation = MagicMock()
    message.conversation.workspace_id = uuid.uuid4()

    push_db = _make_db(execute_returns=[_Result(scalar=message)])
    _patch_session_local(monkeypatch, push_db)

    monkeypatch.setattr(app_settings, "telnyx_api_key", "test-key")

    voice_service = MagicMock()
    voice_service.hangup_call = AsyncMock(return_value=True)
    voice_service.close = AsyncMock(return_value=None)
    from app.services.telephony import telnyx_voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "TelnyxVoiceService",
        lambda *a, **kw: voice_service,
    )

    from app.services.campaigns import sms_fallback

    trigger_fallback = AsyncMock(return_value=None)
    monkeypatch.setattr(
        sms_fallback,
        "trigger_sms_fallback_for_call",
        trigger_fallback,
    )

    await handlers.handle_machine_detection(machine_detection, _make_log())

    voice_service.hangup_call.assert_awaited_once_with(
        "v3:call-control-id-machine-001",
    )
    trigger_fallback.assert_awaited_once()


# --------------------------------------------------------------------------- #
# Warm transfer: closer leg answered (briefing) + speak ended (bridge)
# --------------------------------------------------------------------------- #


async def test_call_answered_transfer_leg_speaks_briefing_and_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
    call_answered: dict[str, Any],
) -> None:
    """When the answered leg is a pending warm-transfer closer leg, speak the
    briefing and skip the normal AI streaming path."""
    from app.services.telephony import call_transfer as ct_module
    from app.services.telephony import telnyx_voice as voice_module

    pending = ct_module.PendingTransfer(
        caller_call_control_id="caller-leg",
        closer_call_control_id="v3:call-control-id-initiated-001",
        workspace_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        mode="warm",
        briefing="Connecting you to Jane Doe. They want premium pricing.",
        language="en-US",
        created_at="2026-06-05T00:00:00+00:00",
    )
    monkeypatch.setattr(ct_module, "peek_pending_transfer", AsyncMock(return_value=pending))
    monkeypatch.setattr(app_settings, "telnyx_api_key", "test-key")

    voice_service = MagicMock()
    voice_service.speak_text = AsyncMock(return_value=True)
    voice_service.bridge_calls = AsyncMock(return_value=True)
    voice_service.close = AsyncMock(return_value=None)
    monkeypatch.setattr(voice_module, "TelnyxVoiceService", lambda *a, **kw: voice_service)

    # AsyncSessionLocal must NOT be used on the transfer-leg short-circuit path.
    def _boom() -> Any:
        raise AssertionError("normal call flow should not run for transfer legs")

    monkeypatch.setattr(handlers, "AsyncSessionLocal", _boom)

    await handlers.handle_call_answered(call_answered, _make_log())

    voice_service.speak_text.assert_awaited_once()
    speak_kwargs = voice_service.speak_text.await_args.kwargs
    assert speak_kwargs["call_control_id"] == "v3:call-control-id-initiated-001"
    assert "Jane Doe" in speak_kwargs["text"]
    # Bridge happens later (on speak.ended), not here.
    voice_service.bridge_calls.assert_not_awaited()


async def test_call_answered_transfer_leg_bridges_now_if_speak_fails(
    monkeypatch: pytest.MonkeyPatch,
    call_answered: dict[str, Any],
) -> None:
    """If briefing speech can't start, bridge immediately so the caller still
    reaches a human."""
    from app.services.telephony import call_transfer as ct_module
    from app.services.telephony import telnyx_voice as voice_module

    pending = ct_module.PendingTransfer(
        caller_call_control_id="caller-leg",
        closer_call_control_id="v3:call-control-id-initiated-001",
        workspace_id=str(uuid.uuid4()),
        agent_id=None,
        mode="warm",
        briefing="brief",
        language="en-US",
        created_at="2026-06-05T00:00:00+00:00",
    )
    monkeypatch.setattr(ct_module, "peek_pending_transfer", AsyncMock(return_value=pending))
    monkeypatch.setattr(app_settings, "telnyx_api_key", "test-key")

    voice_service = MagicMock()
    voice_service.speak_text = AsyncMock(return_value=False)
    voice_service.bridge_calls = AsyncMock(return_value=True)
    voice_service.close = AsyncMock(return_value=None)
    monkeypatch.setattr(voice_module, "TelnyxVoiceService", lambda *a, **kw: voice_service)

    await handlers.handle_call_answered(call_answered, _make_log())

    voice_service.bridge_calls.assert_awaited_once()
    bridge_kwargs = voice_service.bridge_calls.await_args.kwargs
    assert bridge_kwargs["call_control_id"] == "v3:call-control-id-initiated-001"
    assert bridge_kwargs["other_call_control_id"] == "caller-leg"


async def test_speak_ended_bridges_warm_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """call.speak.ended on a pending closer leg bridges it into the caller."""
    from app.services.telephony import call_transfer as ct_module
    from app.services.telephony import telnyx_voice as voice_module

    pending = ct_module.PendingTransfer(
        caller_call_control_id="caller-leg",
        closer_call_control_id="closer-leg",
        workspace_id=str(uuid.uuid4()),
        agent_id=None,
        mode="warm",
        briefing="brief",
        language="en-US",
        created_at="2026-06-05T00:00:00+00:00",
    )
    monkeypatch.setattr(ct_module, "pop_pending_transfer", AsyncMock(return_value=pending))
    monkeypatch.setattr(app_settings, "telnyx_api_key", "test-key")

    voice_service = MagicMock()
    voice_service.bridge_calls = AsyncMock(return_value=True)
    voice_service.close = AsyncMock(return_value=None)
    monkeypatch.setattr(voice_module, "TelnyxVoiceService", lambda *a, **kw: voice_service)

    payload = {"call_control_id": "closer-leg", "status": "completed"}
    await handlers.handle_speak_ended(payload, _make_log())

    voice_service.bridge_calls.assert_awaited_once_with(
        call_control_id="closer-leg",
        other_call_control_id="caller-leg",
    )


async def test_speak_ended_ignores_non_transfer_speak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary speak.ended events (no pending transfer) are a no-op."""
    from app.services.telephony import call_transfer as ct_module
    from app.services.telephony import telnyx_voice as voice_module

    monkeypatch.setattr(ct_module, "pop_pending_transfer", AsyncMock(return_value=None))

    voice_service = MagicMock()
    voice_service.bridge_calls = AsyncMock(return_value=True)
    voice_service.close = AsyncMock(return_value=None)
    monkeypatch.setattr(voice_module, "TelnyxVoiceService", lambda *a, **kw: voice_service)

    await handlers.handle_speak_ended({"call_control_id": "some-leg"}, _make_log())

    voice_service.bridge_calls.assert_not_awaited()


# --------------------------------------------------------------------------- #
# handle_recording_saved (AI voicemail pipeline dispatch)
# --------------------------------------------------------------------------- #


@pytest.fixture
def recording_saved() -> dict[str, Any]:
    return load_telnyx_payload("call_recording_saved.json")


async def test_recording_saved_missing_fields_is_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.telephony import voicemail as vm_module

    process = AsyncMock(return_value=False)
    monkeypatch.setattr(vm_module, "process_voicemail_recording", process)

    await handlers.handle_recording_saved({"call_control_id": ""}, _make_log())

    process.assert_not_awaited()


async def test_recording_saved_voicemail_client_state_runs_followup(
    monkeypatch: pytest.MonkeyPatch,
    recording_saved: dict[str, Any],
) -> None:
    """A voicemail-tagged recording dispatches with ``run_followup=True``."""
    from app.services.telephony import voicemail as vm_module

    process = AsyncMock(return_value=True)
    monkeypatch.setattr(vm_module, "process_voicemail_recording", process)
    # AsyncSessionLocal must NOT be needed when the client_state already marks
    # the recording as a voicemail.
    monkeypatch.setattr(
        handlers,
        "AsyncSessionLocal",
        MagicMock(side_effect=AssertionError("no db lookup needed")),
    )

    await handlers.handle_recording_saved(recording_saved, _make_log())

    process.assert_awaited_once()
    kwargs = process.await_args.kwargs
    assert kwargs["call_control_id"] == "v3:call-control-id-voicemail-001"
    assert kwargs["recording_url"].endswith(".mp3")
    assert kwargs["run_followup"] is True


async def test_recording_saved_inbound_unanswered_runs_followup_via_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No client_state marker, but an unanswered inbound call -> voicemail."""
    from app.services.telephony import voicemail as vm_module

    process = AsyncMock(return_value=True)
    monkeypatch.setattr(vm_module, "process_voicemail_recording", process)

    db = _make_db(execute_returns=[_Result(scalar=None)])
    db.execute = AsyncMock(
        return_value=type("_R", (), {"first": lambda self: ("inbound", "no_answer")})()
    )
    _patch_session_local(monkeypatch, db)

    payload = {
        "call_control_id": "v3:cc-rec-001",
        "client_state": None,
        "recording_urls": {"mp3": "https://x/rec.mp3"},
    }
    await handlers.handle_recording_saved(payload, _make_log())

    process.assert_awaited_once()
    assert process.await_args.kwargs["run_followup"] is True


async def test_recording_saved_answered_call_skips_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An answered (completed) call recording is transcribed but not triaged."""
    from app.services.telephony import voicemail as vm_module

    process = AsyncMock(return_value=True)
    monkeypatch.setattr(vm_module, "process_voicemail_recording", process)

    db = _make_db(execute_returns=[])
    db.execute = AsyncMock(
        return_value=type("_R", (), {"first": lambda self: ("outbound", "completed")})()
    )
    _patch_session_local(monkeypatch, db)

    payload = {
        "call_control_id": "v3:cc-rec-002",
        "client_state": None,
        "recording_urls": {"mp3": "https://x/rec.mp3"},
    }
    await handlers.handle_recording_saved(payload, _make_log())

    process.assert_awaited_once()
    assert process.await_args.kwargs["run_followup"] is False
