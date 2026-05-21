"""Tests for the Mac relay webhook boundary."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.webhooks import mac_relay as mac_relay_module
from app.api.webhooks import mac_relay_handlers as handlers
from app.api.webhooks.mac_relay import router as mac_relay_router
from app.core.config import settings as app_settings
from app.models.conversation import Message, MessageChannel


@asynccontextmanager
async def _test_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(mac_relay_router, prefix="/webhooks/mac-relay")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


async def test_missing_webhook_token_returns_503(client: AsyncClient) -> None:
    with (
        patch.object(app_settings, "mac_relay_webhook_token", ""),
        patch.object(app_settings, "mac_relay_token", ""),
    ):
        response = await client.post("/webhooks/mac-relay/messages", json={})

    assert response.status_code == 503


async def test_invalid_webhook_token_returns_401(client: AsyncClient) -> None:
    with patch.object(app_settings, "mac_relay_webhook_token", "expected-token"):
        response = await client.post(
            "/webhooks/mac-relay/messages",
            json={"event_id": "evt-1"},
            headers={"Authorization": "Bearer wrong-token"},
        )

    assert response.status_code == 401


async def test_authenticated_webhook_dispatches_to_handler(client: AsyncClient) -> None:
    mock_handle = AsyncMock(return_value={"status": "ok"})
    payload = {"event_id": "evt-1", "is_from_me": True}

    with (
        patch.object(app_settings, "mac_relay_webhook_token", "expected-token"),
        patch.object(mac_relay_module, "handle_mac_relay_message", mock_handle),
    ):
        response = await client.post(
            "/webhooks/mac-relay/messages",
            json=payload,
            headers={"Authorization": "Bearer expected-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_handle.assert_awaited_once()
    assert mock_handle.await_args.args[0] == payload


async def test_handler_ignores_outbound_echo() -> None:
    log = _make_log()
    result = await handlers.handle_mac_relay_message(
        {"event_id": "evt-1", "is_from_me": True},
        log,
    )

    assert result == {"status": "ignored", "reason": "outbound_echo"}


async def test_process_inbound_mac_relay_message_prefixes_provider_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = MagicMock(spec=Message)
    expected.provider_message_id = "mac-relay:relay-guid-1"
    expected.channel = MessageChannel.IMESSAGE

    persist = AsyncMock(return_value=expected)
    monkeypatch.setattr(handlers, "persist_inbound_text_message", persist)

    workspace_id = uuid.uuid4()
    result = await handlers.process_inbound_mac_relay_message(
        db=MagicMock(),
        provider_message_id="relay-guid-1",
        from_number="+14155552671",
        to_number="+12125550101",
        body="hello",
        workspace_id=workspace_id,
    )

    assert result is expected
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["provider_message_id"] == "mac-relay:relay-guid-1"
    assert persist.await_args.kwargs["channel"] == MessageChannel.IMESSAGE


async def test_handler_dedupes_existing_provider_message(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.phone_number = "+12125550101"
    phone_record.workspace_id = workspace_id
    existing_message = MagicMock(spec=Message)

    db = _make_db(execute_returns=[_Result(scalar=phone_record), _Result(scalar=existing_message)])
    _patch_session_local(monkeypatch, db)

    process_pipeline = AsyncMock()
    monkeypatch.setattr(handlers, "process_inbound_text_event", process_pipeline)

    result = await handlers.handle_mac_relay_message(
        {
            "guid": "relay-guid-1",
            "from": "+14155552671",
            "to": "+12125550101",
            "text": "hello",
            "is_from_me": False,
        },
        _make_log(),
    )

    assert result == {"status": "ok", "reason": "duplicate"}
    process_pipeline.assert_not_awaited()


async def test_handler_processes_inbound_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_id = uuid.uuid4()
    phone_record = MagicMock()
    phone_record.phone_number = "+12125550101"
    phone_record.workspace_id = workspace_id

    db = _make_db(execute_returns=[_Result(scalar=phone_record), _Result(scalar=None)])
    _patch_session_local(monkeypatch, db)

    captured_event: Any = None

    async def fake_process_inbound_text_event(**kwargs: Any) -> MagicMock:
        nonlocal captured_event
        captured_event = kwargs["event"]
        message = MagicMock()
        message.id = uuid.uuid4()
        message.conversation_id = uuid.uuid4()
        return message

    monkeypatch.setattr(
        handlers,
        "process_inbound_text_event",
        fake_process_inbound_text_event,
    )

    result = await handlers.handle_mac_relay_message(
        {
            "event_id": "evt-1",
            "guid": "relay-guid-1",
            "from": "+14155552671",
            "to": "+12125550101",
            "text": "hello",
            "is_from_me": False,
            "service": "imessage",
        },
        _make_log(),
    )

    assert result["status"] == "ok"
    assert captured_event.provider_message_id == "mac-relay:relay-guid-1"
    assert captured_event.from_number == "+14155552671"
    assert captured_event.to_number == "+12125550101"
    assert captured_event.body == "hello"
    assert captured_event.workspace_id == workspace_id
    assert captured_event.channel == MessageChannel.IMESSAGE


class _Result:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


def _make_db(execute_returns: list[Any]) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(execute_returns))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
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
