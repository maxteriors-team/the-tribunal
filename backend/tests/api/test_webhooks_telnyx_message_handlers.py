"""Tests for ``app.api.webhooks.telnyx_message_handlers``.

Covers:

- ``handle_inbound_message`` — phone-number resolution, approval-command
  short-circuit, operator detection (workspace member texting their own
  number), and the inbound-message → AI-response scheduling pipeline.
- ``handle_delivery_status`` — bounce classification via
  ``BounceClassifier``, reputation tracker updates, and campaign
  delivery-stats forwarding.

All external services are stubbed at the module level. Real Telnyx
payload shapes are loaded from ``tests/fixtures/webhooks/telnyx/``.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.webhooks import telnyx_message_handlers as handlers
from app.core.config import settings as app_settings
from app.services.telephony.inbound_text import InboundMessageIngestResult
from tests.fixtures.webhooks import load_telnyx_payload

# --------------------------------------------------------------------------- #
# Shared mock plumbing
# --------------------------------------------------------------------------- #


class _Result:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


def _make_db(execute_returns: list[Any]) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(execute_returns))
    db.commit = AsyncMock()
    db.add = MagicMock()
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
def _stub_modules(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Silence external services unless a test re-enables them."""
    stubs: dict[str, MagicMock] = {}

    # Telnyx API key must be set so the handler doesn't bail before processing.
    monkeypatch.setattr(app_settings, "telnyx_api_key", "test-key")

    command_proc = MagicMock()
    command_proc.try_process_command = AsyncMock(return_value=False)
    monkeypatch.setattr(handlers, "command_processor_service", command_proc)
    stubs["command_processor_service"] = command_proc

    schedule_ai = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "schedule_ai_response", schedule_ai)
    stubs["schedule_ai_response"] = schedule_ai

    syncer = MagicMock()
    syncer.sync_conversation = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "_conversation_syncer", syncer)
    stubs["conversation_syncer"] = syncer

    push = MagicMock()
    push.send_to_workspace_members = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "push_notification_service", push)
    stubs["push"] = push

    observe = MagicMock(return_value=None)
    monkeypatch.setattr(handlers, "observe_sms_bounce", observe)
    stubs["observe_sms_bounce"] = observe

    return stubs


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def sms_inbound() -> dict[str, Any]:
    return load_telnyx_payload("sms_inbound.json")


@pytest.fixture
def sms_delivered() -> dict[str, Any]:
    return load_telnyx_payload("sms_delivered.json")


@pytest.fixture
def sms_failed_hard_bounce() -> dict[str, Any]:
    return load_telnyx_payload("sms_failed_hard_bounce.json")


@pytest.fixture
def sms_failed_spam() -> dict[str, Any]:
    return load_telnyx_payload("sms_failed_spam.json")


@pytest.fixture
def sms_failed_soft() -> dict[str, Any]:
    return load_telnyx_payload("sms_failed_soft.json")


# --------------------------------------------------------------------------- #
# handle_inbound_message
# --------------------------------------------------------------------------- #


async def test_inbound_message_returns_when_required_fields_missing() -> None:
    """Missing from/to/body → warn and bail before opening a session."""
    log = _make_log()

    await handlers.handle_inbound_message({"from": {}, "to": [], "text": ""}, log)

    log.warning.assert_any_call("missing_required_fields")


def test_extract_inbound_media_normalizes_provider_metadata() -> None:
    media = handlers._extract_inbound_media(
        {
            "media": [
                {
                    "url": "https://media.telnyx.com/inbound/photo?token=opaque",
                    "content_type": "Image/JPEG; charset=binary",
                    "size": 1234,
                    "sha256": "A" * 64,
                },
                {"url": "http://localhost/private", "content_type": "image/png"},
                {"url": "https://media.telnyx.com/file", "size": True},
                "invalid",
            ]
        }
    )

    assert len(media) == 2
    assert media[0].source_url.endswith("?token=opaque")
    assert media[0].content_type == "image/jpeg"
    assert media[0].size_bytes == 1234
    assert media[0].sha256 == "a" * 64
    assert media[1].content_type == "application/octet-stream"
    assert media[1].size_bytes is None


async def test_inbound_media_only_message_is_ingested(
    monkeypatch: pytest.MonkeyPatch,
    _stub_modules: dict[str, MagicMock],
) -> None:
    workspace_id = uuid.uuid4()
    phone_record = MagicMock(workspace_id=workspace_id)
    db = _make_db(execute_returns=[_Result(scalar=phone_record)])
    _patch_session_local(monkeypatch, db)

    ingested_message = MagicMock(id=uuid.uuid4())
    sms_service = MagicMock()
    sms_service.process_inbound_message = AsyncMock(
        return_value=InboundMessageIngestResult(ingested_message, created=True)
    )
    sms_service.close = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "TelnyxSMSService", lambda *args, **kwargs: sms_service)

    captured_event = None

    async def fake_pipeline(**kwargs: Any) -> MagicMock:
        nonlocal captured_event
        captured_event = kwargs["event"]
        result = await kwargs["ingest_message"](kwargs["db"], captured_event)
        return result.message

    monkeypatch.setattr(handlers, "process_inbound_text_event", fake_pipeline)
    payload = {
        "id": "message-media-only",
        "from": {"phone_number": "+14155552671"},
        "to": [{"phone_number": "+12125550101"}],
        "text": "",
        "media": [
            {
                "url": "https://media.telnyx.com/inbound/photo.jpg",
                "content_type": "image/jpeg",
                "size": 321,
            }
        ],
    }

    await handlers.handle_inbound_message(payload, _make_log())

    assert captured_event is not None
    assert captured_event.body == ""
    assert captured_event.media_count == 1
    assert captured_event.media_preview == "Photo received"
    call = sms_service.process_inbound_message.await_args.kwargs
    assert len(call["media"]) == 1
    assert call["media"][0].content_type == "image/jpeg"
    _stub_modules["command_processor_service"].try_process_command.assert_not_awaited()


async def test_inbound_message_returns_when_phone_number_unknown(
    monkeypatch: pytest.MonkeyPatch,
    sms_inbound: dict[str, Any],
) -> None:
    db = _make_db(execute_returns=[_Result(scalar=None)])  # PhoneNumber miss
    _patch_session_local(monkeypatch, db)
    log = _make_log()

    await handlers.handle_inbound_message(sms_inbound, log)

    log.warning.assert_any_call(
        "phone_number_not_found",
        to_number="+12125550101",
    )


async def test_inbound_message_approval_command_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
    sms_inbound: dict[str, Any],
    _stub_modules: dict[str, MagicMock],
) -> None:
    """A ``Y``/approve reply must be consumed by the approval-command
    processor BEFORE we ingest it as a normal inbound message.
    """
    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id

    db = _make_db(execute_returns=[_Result(scalar=phone_record)])
    _patch_session_local(monkeypatch, db)

    _stub_modules["command_processor_service"].try_process_command = AsyncMock(
        return_value=True,
    )

    log = _make_log()
    await handlers.handle_inbound_message(sms_inbound, log)

    _stub_modules["command_processor_service"].try_process_command.assert_awaited_once()
    log.info.assert_any_call("processed_approval_command", from_number="+14155552671")
    # No AI scheduling or push when the message is consumed by the command processor.
    _stub_modules["schedule_ai_response"].assert_not_awaited()
    _stub_modules["push"].send_to_workspace_members.assert_not_awaited()


async def test_inbound_message_operator_routes_to_crm_assistant(
    monkeypatch: pytest.MonkeyPatch,
    sms_inbound: dict[str, Any],
    _stub_modules: dict[str, MagicMock],
) -> None:
    """A workspace member texting their own number must hit the CRM
    assistant, not the contact-conversation pipeline.
    """
    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id

    operator = MagicMock()
    operator.id = uuid.uuid4()
    operator.phone_number = "+14155552671"

    # Execute order:
    #   1. PhoneNumber lookup
    #   2. _check_operator User SELECT (returns the workspace member)
    #   3. membership role SELECT (the assistant runs with the texter's role)
    db = _make_db(
        execute_returns=[
            _Result(scalar=phone_record),
            _Result(scalar=operator),
            _Result(scalar="manager"),
        ]
    )
    _patch_session_local(monkeypatch, db)

    from app.services.ai import crm_assistant

    process_assistant = AsyncMock(return_value=None)
    monkeypatch.setattr(crm_assistant, "process_assistant_message", process_assistant)

    await handlers.handle_inbound_message(sms_inbound, _make_log())

    process_assistant.assert_awaited_once()
    # Texting the assistant is the same privileged surface as the in-app chat,
    # so it must carry the texter's real role rather than an implied admin one.
    assert process_assistant.await_args.kwargs["role"] == "manager"
    # Operator path must NOT re-enter the contact AI pipeline.
    _stub_modules["schedule_ai_response"].assert_not_awaited()


async def test_inbound_message_processes_and_schedules_ai_response(
    monkeypatch: pytest.MonkeyPatch,
    sms_inbound: dict[str, Any],
    _stub_modules: dict[str, MagicMock],
) -> None:
    """Happy path: not a command, not an operator → ingest + schedule AI."""
    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id

    conversation = MagicMock()
    conversation.id = uuid.uuid4()
    conversation.ai_enabled = True
    conversation.ai_paused = False
    conversation.assigned_agent_id = None
    conversation.contact_id = 42

    ingested_message = MagicMock()
    ingested_message.id = uuid.uuid4()
    ingested_message.conversation_id = conversation.id

    # Execute order (operator MISS, then conversation lookups):
    #   1. PhoneNumber lookup
    #   2. _check_operator → User miss
    #   3. Conversation lookup (post-ingest)
    #   4. Conversation lookup (drip-pause branch)
    db = _make_db(
        execute_returns=[
            _Result(scalar=phone_record),
            _Result(scalar=None),
            _Result(scalar=conversation),
            _Result(scalar=conversation),
        ]
    )
    _patch_session_local(monkeypatch, db)

    sms_service = MagicMock()
    sms_service.process_inbound_message = AsyncMock(
        return_value=InboundMessageIngestResult(ingested_message, created=True)
    )
    sms_service.close = AsyncMock(return_value=None)
    monkeypatch.setattr(
        handlers,
        "TelnyxSMSService",
        lambda *a, **kw: sms_service,
    )

    # Silence drip-pause + campaign-reply side effects (already a try/except).
    from app.services.campaigns import campaign_sms_stats
    from app.services.reactivation import drip_runner

    monkeypatch.setattr(
        drip_runner,
        "handle_inbound_reply",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        campaign_sms_stats,
        "update_campaign_sms_reply",
        AsyncMock(return_value=None),
    )

    await handlers.handle_inbound_message(sms_inbound, _make_log())

    sms_service.process_inbound_message.assert_awaited_once()
    _stub_modules["conversation_syncer"].sync_conversation.assert_awaited_once()
    _stub_modules["schedule_ai_response"].assert_awaited_once()
    _stub_modules["push"].send_to_workspace_members.assert_awaited_once()


async def test_inbound_message_skips_ai_when_paused(
    monkeypatch: pytest.MonkeyPatch,
    sms_inbound: dict[str, Any],
    _stub_modules: dict[str, MagicMock],
) -> None:
    """Paused conversations must NOT schedule an AI reply."""
    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.workspace_id = workspace_id

    conversation = MagicMock()
    conversation.id = uuid.uuid4()
    conversation.ai_enabled = True
    conversation.ai_paused = True
    conversation.contact_id = 42

    ingested_message = MagicMock()
    ingested_message.id = uuid.uuid4()
    ingested_message.conversation_id = conversation.id

    db = _make_db(
        execute_returns=[
            _Result(scalar=phone_record),
            _Result(scalar=None),  # operator miss
            _Result(scalar=conversation),
            _Result(scalar=conversation),
        ]
    )
    _patch_session_local(monkeypatch, db)

    sms_service = MagicMock()
    sms_service.process_inbound_message = AsyncMock(
        return_value=InboundMessageIngestResult(ingested_message, created=True)
    )
    sms_service.close = AsyncMock(return_value=None)
    monkeypatch.setattr(
        handlers,
        "TelnyxSMSService",
        lambda *a, **kw: sms_service,
    )

    from app.services.campaigns import campaign_sms_stats
    from app.services.reactivation import drip_runner

    monkeypatch.setattr(
        drip_runner,
        "handle_inbound_reply",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        campaign_sms_stats,
        "update_campaign_sms_reply",
        AsyncMock(return_value=None),
    )

    await handlers.handle_inbound_message(sms_inbound, _make_log())

    _stub_modules["schedule_ai_response"].assert_not_awaited()


# --------------------------------------------------------------------------- #
# handle_delivery_status — bounce classification
# --------------------------------------------------------------------------- #


def _make_outbound_message(
    *,
    status: str = "delivered",
    from_phone_number_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> MagicMock:
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.status = status
    msg.from_phone_number_id = from_phone_number_id
    msg.conversation_id = conversation_id
    msg.bounce_type = None
    msg.bounce_category = None
    msg.carrier_error_code = None
    return msg


def _stub_telnyx_sms_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    message: MagicMock,
    previous_status: str | None = None,
) -> MagicMock:
    service = MagicMock()
    service.update_message_status = AsyncMock(
        return_value=(message, previous_status),
    )
    service.close = AsyncMock(return_value=None)
    monkeypatch.setattr(
        handlers,
        "TelnyxSMSService",
        lambda *a, **kw: service,
    )
    return service


def _stub_reputation_tracker(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ReputationTracker to a single mock instance the test can assert on."""
    tracker = MagicMock()
    tracker.increment_delivered = AsyncMock(return_value=None)
    tracker.increment_hard_bounce = AsyncMock(return_value=None)
    tracker.increment_soft_bounce = AsyncMock(return_value=None)
    tracker.increment_spam_complaint = AsyncMock(return_value=None)

    from app.services.rate_limiting import reputation_tracker as tracker_mod

    monkeypatch.setattr(
        tracker_mod,
        "ReputationTracker",
        lambda *a, **kw: tracker,
    )
    return tracker


async def test_delivery_status_delivered_increments_reputation(
    monkeypatch: pytest.MonkeyPatch,
    sms_delivered: dict[str, Any],
) -> None:
    phone_number_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    message = _make_outbound_message(
        status="delivered",
        from_phone_number_id=phone_number_id,
        conversation_id=conv_id,
    )

    db = _make_db(execute_returns=[])
    _patch_session_local(monkeypatch, db)
    _stub_telnyx_sms_service(
        monkeypatch,
        message=message,
        previous_status="sent",
    )
    tracker = _stub_reputation_tracker(monkeypatch)

    from app.services.campaigns import campaign_sms_stats

    update_delivery = AsyncMock(return_value=None)
    monkeypatch.setattr(
        campaign_sms_stats,
        "update_campaign_sms_delivery",
        update_delivery,
    )

    await handlers.handle_delivery_status(sms_delivered, _make_log())

    tracker.increment_delivered.assert_awaited_once_with(phone_number_id, db)
    tracker.increment_hard_bounce.assert_not_awaited()
    update_delivery.assert_awaited_once()
    call = update_delivery.await_args
    assert call is not None
    assert call.kwargs["delivered"] is True
    assert call.kwargs["previous_status"] == "sent"


async def test_delivery_status_hard_bounce_classifies_and_tracks(
    monkeypatch: pytest.MonkeyPatch,
    sms_failed_hard_bounce: dict[str, Any],
    _stub_modules: dict[str, MagicMock],
) -> None:
    """30004 (invalid number) → hard bounce. Must classify the message,
    bump the hard-bounce counter, and emit the Prometheus metric.
    """
    phone_number_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    message = _make_outbound_message(
        status="failed",
        from_phone_number_id=phone_number_id,
        conversation_id=uuid.uuid4(),
    )
    phone_row = MagicMock()
    phone_row.workspace_id = workspace_id

    db = _make_db(execute_returns=[])
    db.get = AsyncMock(return_value=phone_row)
    _patch_session_local(monkeypatch, db)
    _stub_telnyx_sms_service(monkeypatch, message=message)
    tracker = _stub_reputation_tracker(monkeypatch)

    from app.services.campaigns import campaign_sms_stats

    monkeypatch.setattr(
        campaign_sms_stats,
        "update_campaign_sms_delivery",
        AsyncMock(return_value=None),
    )

    await handlers.handle_delivery_status(sms_failed_hard_bounce, _make_log())

    assert message.bounce_type == "hard"
    assert message.bounce_category == "invalid_number"
    assert message.carrier_error_code == "30004"
    tracker.increment_hard_bounce.assert_awaited_once_with(phone_number_id, db)
    tracker.increment_soft_bounce.assert_not_awaited()
    _stub_modules["observe_sms_bounce"].assert_called_once_with(
        workspace_id,
        bounce_type="hard",
    )


async def test_delivery_status_spam_complaint_classifies_correctly(
    monkeypatch: pytest.MonkeyPatch,
    sms_failed_spam: dict[str, Any],
    _stub_modules: dict[str, MagicMock],
) -> None:
    """40001 (spam block) → spam_complaint bounce."""
    phone_number_id = uuid.uuid4()
    message = _make_outbound_message(
        status="failed",
        from_phone_number_id=phone_number_id,
        conversation_id=uuid.uuid4(),
    )

    db = _make_db(execute_returns=[])
    db.get = AsyncMock(return_value=MagicMock(workspace_id=uuid.uuid4()))
    _patch_session_local(monkeypatch, db)
    _stub_telnyx_sms_service(monkeypatch, message=message)
    tracker = _stub_reputation_tracker(monkeypatch)

    from app.services.campaigns import campaign_sms_stats

    monkeypatch.setattr(
        campaign_sms_stats,
        "update_campaign_sms_delivery",
        AsyncMock(return_value=None),
    )

    await handlers.handle_delivery_status(sms_failed_spam, _make_log())

    assert message.bounce_type == "spam_complaint"
    tracker.increment_spam_complaint.assert_awaited_once()
    tracker.increment_hard_bounce.assert_not_awaited()


async def test_delivery_status_soft_bounce_classifies_correctly(
    monkeypatch: pytest.MonkeyPatch,
    sms_failed_soft: dict[str, Any],
) -> None:
    """40201 (carrier timeout) → soft bounce."""
    phone_number_id = uuid.uuid4()
    message = _make_outbound_message(
        status="failed",
        from_phone_number_id=phone_number_id,
        conversation_id=uuid.uuid4(),
    )

    db = _make_db(execute_returns=[])
    db.get = AsyncMock(return_value=MagicMock(workspace_id=uuid.uuid4()))
    _patch_session_local(monkeypatch, db)
    _stub_telnyx_sms_service(monkeypatch, message=message)
    tracker = _stub_reputation_tracker(monkeypatch)

    from app.services.campaigns import campaign_sms_stats

    monkeypatch.setattr(
        campaign_sms_stats,
        "update_campaign_sms_delivery",
        AsyncMock(return_value=None),
    )

    await handlers.handle_delivery_status(sms_failed_soft, _make_log())

    assert message.bounce_type == "soft"
    assert message.bounce_category == "carrier_timeout"
    tracker.increment_soft_bounce.assert_awaited_once()


async def test_delivery_status_skips_campaign_stats_for_non_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sent``/``queued`` statuses must NOT touch campaign delivery stats."""
    message = _make_outbound_message(
        status="queued",
        from_phone_number_id=None,
        conversation_id=uuid.uuid4(),
    )
    payload = {
        "id": "msg-q-001",
        "to": [{"phone_number": "+14155552671", "status": "queued"}],
        "errors": [],
    }

    db = _make_db(execute_returns=[])
    _patch_session_local(monkeypatch, db)
    _stub_telnyx_sms_service(monkeypatch, message=message)

    from app.services.campaigns import campaign_sms_stats

    update_delivery = AsyncMock(return_value=None)
    monkeypatch.setattr(
        campaign_sms_stats,
        "update_campaign_sms_delivery",
        update_delivery,
    )

    await handlers.handle_delivery_status(payload, _make_log())

    update_delivery.assert_not_awaited()
