"""Tests for ``app.services.telephony.missed_call_textback``.

Covers the pure helpers (settings parsing, template render, quiet hours) and
the orchestration of ``send_missed_call_textback`` with mocked DB + delivery:

* enabled/disabled gating
* idempotent, opt-out, and quiet-hours suppression
* only-inbound + only-missed-outcome guards
* the SMS lands and the conversation is left in AI SMS mode so the reply
  re-enters the bot.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

import app.services.telephony.missed_call_textback as mod
from app.models.conversation import MessageChannel, MessageDirection
from app.services.outbound.delivery import (
    OutboundDeliveryChannel,
    OutboundDeliveryResult,
    OutboundDeliveryStatus,
)
from app.services.telephony.missed_call_textback import (
    DEFAULT_TEMPLATE,
    MissedCallTextbackSettings,
    get_missed_call_textback_settings,
    is_within_quiet_hours,
    render_textback_template,
    send_missed_call_textback,
)


def _make_log() -> MagicMock:
    log = MagicMock()
    log.bind = MagicMock(return_value=log)
    return log


# --------------------------------------------------------------------------- #
# Settings parsing
# --------------------------------------------------------------------------- #


class TestSettings:
    def test_defaults_when_unset(self) -> None:
        ws = SimpleNamespace(settings={})
        cfg = get_missed_call_textback_settings(ws)  # type: ignore[arg-type]
        assert cfg.enabled is False
        assert cfg.template == DEFAULT_TEMPLATE

    def test_reads_enabled_and_template(self) -> None:
        ws = SimpleNamespace(
            settings={
                "missed_call_textback": {
                    "enabled": True,
                    "template": "Hi {first_name}!",
                    "quiet_hours_start": "21:00",
                    "quiet_hours_end": "08:00",
                    "timezone": "America/New_York",
                }
            }
        )
        cfg = get_missed_call_textback_settings(ws)  # type: ignore[arg-type]
        assert cfg.enabled is True
        assert cfg.template == "Hi {first_name}!"
        assert cfg.quiet_hours_start == "21:00"
        assert cfg.timezone == "America/New_York"

    def test_blank_template_falls_back_to_default(self) -> None:
        ws = SimpleNamespace(settings={"missed_call_textback": {"template": ""}})
        cfg = get_missed_call_textback_settings(ws)  # type: ignore[arg-type]
        assert cfg.template == DEFAULT_TEMPLATE

    def test_non_dict_block_is_ignored(self) -> None:
        ws = SimpleNamespace(settings={"missed_call_textback": "nope"})
        cfg = get_missed_call_textback_settings(ws)  # type: ignore[arg-type]
        assert cfg.enabled is False


# --------------------------------------------------------------------------- #
# Template rendering
# --------------------------------------------------------------------------- #


class TestRender:
    def test_default_template_has_no_placeholders(self) -> None:
        assert render_textback_template(DEFAULT_TEMPLATE, None) == DEFAULT_TEMPLATE

    def test_renders_contact_fields(self) -> None:
        contact = SimpleNamespace(first_name="Alice", last_name="Smith", company_name="Acme")
        out = render_textback_template("Hi {first_name} from {company_name}", contact)  # type: ignore[arg-type]
        assert out == "Hi Alice from Acme"

    def test_missing_contact_fields_render_blank(self) -> None:
        out = render_textback_template("Hi {first_name}", None)
        assert out == "Hi"


# --------------------------------------------------------------------------- #
# Quiet hours
# --------------------------------------------------------------------------- #


class TestQuietHours:
    def _ws(self, tz: str = "UTC") -> Any:
        return SimpleNamespace(settings={"timezone": tz})

    def test_no_window_means_never_quiet(self) -> None:
        cfg = MissedCallTextbackSettings(enabled=True)
        assert is_within_quiet_hours(cfg, self._ws()) is False

    def test_overnight_window_inside(self) -> None:
        cfg = MissedCallTextbackSettings(
            enabled=True,
            quiet_hours_start="21:00",
            quiet_hours_end="08:00",
            timezone="UTC",
        )
        now = datetime(2026, 1, 1, 23, 0, tzinfo=ZoneInfo("UTC"))
        assert is_within_quiet_hours(cfg, self._ws(), now) is True

    def test_overnight_window_outside(self) -> None:
        cfg = MissedCallTextbackSettings(
            enabled=True,
            quiet_hours_start="21:00",
            quiet_hours_end="08:00",
            timezone="UTC",
        )
        now = datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        assert is_within_quiet_hours(cfg, self._ws(), now) is False

    def test_same_day_window_inside(self) -> None:
        cfg = MissedCallTextbackSettings(
            enabled=True,
            quiet_hours_start="09:00",
            quiet_hours_end="17:00",
            timezone="UTC",
        )
        now = datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        assert is_within_quiet_hours(cfg, self._ws(), now) is True

    def test_invalid_timezone_falls_back_to_utc(self) -> None:
        cfg = MissedCallTextbackSettings(
            enabled=True,
            quiet_hours_start="21:00",
            quiet_hours_end="08:00",
            timezone="Not/AZone",
        )
        now = datetime(2026, 1, 1, 23, 0, tzinfo=ZoneInfo("UTC"))
        assert is_within_quiet_hours(cfg, self._ws(), now) is True


# --------------------------------------------------------------------------- #
# send_missed_call_textback orchestration
# --------------------------------------------------------------------------- #


class _Result:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


CALL_ID = "v3:missed-call-control-001"
WORKSPACE_ID = uuid.uuid4()
AGENT_ID = uuid.uuid4()


def _build_world(
    *,
    enabled: bool = True,
    direction: str = MessageDirection.INBOUND,
    settings_block: dict[str, Any] | None = None,
    recent_inbound_body: str | None = None,
    contact: Any = None,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Return (db, conversation, message) wired for the happy path."""
    conversation = MagicMock()
    conversation.id = uuid.uuid4()
    conversation.workspace_id = WORKSPACE_ID
    conversation.contact_phone = "+15551230000"
    conversation.workspace_phone = "+15559990000"
    conversation.contact_id = None
    conversation.assigned_agent_id = AGENT_ID
    conversation.channel = MessageChannel.VOICE.value
    conversation.ai_enabled = False
    conversation.ai_paused = False

    message = MagicMock()
    message.direction = direction
    message.conversation = conversation

    workspace = MagicMock()
    block = settings_block if settings_block is not None else {"enabled": enabled}
    workspace.settings = {"missed_call_textback": block, "timezone": "UTC"}

    db = MagicMock()
    # execute() is called for: Message lookup, then recent-inbound opt-out lookup.
    db.execute = AsyncMock(
        side_effect=[
            _Result(scalar=message),
            _Result(scalar=recent_inbound_body),
        ]
    )

    async def _get(model: Any, _id: Any) -> Any:
        name = getattr(model, "__name__", "")
        if name == "Workspace":
            return workspace
        if name == "Conversation":
            return conversation
        if name == "Contact":
            return contact
        return None

    db.get = AsyncMock(side_effect=_get)
    db.commit = AsyncMock()
    return db, conversation, message


def _patch_session(monkeypatch: pytest.MonkeyPatch, db: MagicMock) -> None:
    class _CM:
        async def __aenter__(self) -> MagicMock:
            return db

        async def __aexit__(self, *exc: Any) -> None:
            return None

    import app.db.session as session_mod

    monkeypatch.setattr(session_mod, "AsyncSessionLocal", lambda: _CM())


def _patch_opt_out(monkeypatch: pytest.MonkeyPatch, opted_out: bool = False) -> None:
    manager = MagicMock()
    manager.check_opt_out = AsyncMock(return_value=opted_out)
    monkeypatch.setattr(mod, "_opt_out_manager", manager)


def _patch_delivery(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: OutboundDeliveryStatus = OutboundDeliveryStatus.SENT,
) -> AsyncMock:
    msg = MagicMock()
    msg.id = uuid.uuid4()
    result = OutboundDeliveryResult(
        channel=OutboundDeliveryChannel.SMS,
        status=status,
        message=msg if status is OutboundDeliveryStatus.SENT else None,
        provider="telnyx",
    )
    service = MagicMock()
    service.deliver = AsyncMock(return_value=result)
    monkeypatch.setattr(mod, "outbound_delivery_service", service)
    return service.deliver


async def test_happy_path_sends_and_enters_ai_sms_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, conversation, _ = _build_world()
    _patch_session(monkeypatch, db)
    _patch_opt_out(monkeypatch)
    deliver = _patch_delivery(monkeypatch)

    result = await send_missed_call_textback(CALL_ID, "no_answer", _make_log())

    assert result is True
    deliver.assert_awaited_once()
    request = deliver.await_args.args[1]
    assert request.channel is OutboundDeliveryChannel.SMS
    assert request.to == "+15551230000"
    assert request.from_ == "+15559990000"
    assert request.idempotency_parts == (CALL_ID,)
    assert request.require_sms_consent is False
    # Conversation flipped into AI SMS mode for the reply.
    assert conversation.channel == MessageChannel.SMS.value
    assert conversation.ai_enabled is True


async def test_skips_non_missed_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    deliver = _patch_delivery(monkeypatch)
    # Should bail before touching the DB.
    result = await send_missed_call_textback(CALL_ID, "completed", _make_log())
    assert result is False
    deliver.assert_not_awaited()


async def test_skips_outbound_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    db, _, _ = _build_world(direction=MessageDirection.OUTBOUND)
    _patch_session(monkeypatch, db)
    _patch_opt_out(monkeypatch)
    deliver = _patch_delivery(monkeypatch)

    result = await send_missed_call_textback(CALL_ID, "no_answer", _make_log())

    assert result is False
    deliver.assert_not_awaited()


async def test_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    db, _, _ = _build_world(enabled=False)
    _patch_session(monkeypatch, db)
    _patch_opt_out(monkeypatch)
    deliver = _patch_delivery(monkeypatch)

    result = await send_missed_call_textback(CALL_ID, "no_answer", _make_log())

    assert result is False
    deliver.assert_not_awaited()


async def test_skips_when_opted_out(monkeypatch: pytest.MonkeyPatch) -> None:
    db, _, _ = _build_world()
    _patch_session(monkeypatch, db)
    _patch_opt_out(monkeypatch, opted_out=True)
    deliver = _patch_delivery(monkeypatch)

    result = await send_missed_call_textback(CALL_ID, "no_answer", _make_log())

    assert result is False
    deliver.assert_not_awaited()


async def test_skips_on_recent_inbound_opt_out_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, _, _ = _build_world(recent_inbound_body="STOP")
    _patch_session(monkeypatch, db)
    _patch_opt_out(monkeypatch)
    deliver = _patch_delivery(monkeypatch)

    result = await send_missed_call_textback(CALL_ID, "no_answer", _make_log())

    assert result is False
    deliver.assert_not_awaited()


async def test_skips_during_quiet_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    db, _, _ = _build_world(
        settings_block={
            "enabled": True,
            "quiet_hours_start": "00:00",
            "quiet_hours_end": "23:59",
            "timezone": "UTC",
        }
    )
    _patch_session(monkeypatch, db)
    _patch_opt_out(monkeypatch)
    deliver = _patch_delivery(monkeypatch)

    result = await send_missed_call_textback(CALL_ID, "no_answer", _make_log())

    assert result is False
    deliver.assert_not_awaited()


async def test_blocked_delivery_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    db, _, _ = _build_world()
    _patch_session(monkeypatch, db)
    _patch_opt_out(monkeypatch)
    deliver = _patch_delivery(monkeypatch, status=OutboundDeliveryStatus.BLOCKED)

    result = await send_missed_call_textback(CALL_ID, "no_answer", _make_log())

    assert result is False
    deliver.assert_awaited_once()
