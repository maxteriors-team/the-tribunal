"""Tests for the Mac relay webhook boundary.

The relay authenticates per workspace (audit finding H-4): the presented bearer
token resolves to one ``phone_numbers`` row and *that* row's workspace scopes the
request. These tests pin both halves — the route may not accept an unresolvable
token, and the handler may not act on a number outside the token's workspace.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.webhooks import mac_relay as mac_relay_module
from app.api.webhooks import mac_relay_handlers as handlers
from app.api.webhooks.mac_relay import router as mac_relay_router
from app.core.config import settings as app_settings
from app.models.conversation import Message, MessageChannel
from app.services.telephony.inbound_types import InboundMessageIngestResult
from app.services.telephony.mac_relay_auth import MacRelayCredential


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


# ─── Route: authentication ───────────────────────────────────────────────────


async def test_unprovisioned_relay_returns_503(client: AsyncClient) -> None:
    """No number carries a relay token at all — stay fail-closed with a 503."""
    with _patch_relay_auth(credential=None, configured=False):
        response = await client.post(
            "/webhooks/mac-relay/messages",
            json={"event_id": "evt-1"},
            headers={"Authorization": "Bearer macrelay_whatever"},
        )

    assert response.status_code == 503


async def test_unresolvable_token_returns_401(client: AsyncClient) -> None:
    """Relay tokens exist, but this one resolves to no workspace."""
    with _patch_relay_auth(credential=None, configured=True):
        response = await client.post(
            "/webhooks/mac-relay/messages",
            json={"event_id": "evt-1"},
            headers={"Authorization": "Bearer macrelay_wrong"},
        )

    assert response.status_code == 401


async def test_missing_authorization_header_returns_401(client: AsyncClient) -> None:
    with _patch_relay_auth(credential=None, configured=True) as mocks:
        response = await client.post("/webhooks/mac-relay/messages", json={})

    assert response.status_code == 401
    # An absent header must still be *resolved* (to nothing), never waved through.
    assert mocks["resolve"].await_args.args[1] == ""


async def test_valid_token_dispatches_with_workspace_from_token(client: AsyncClient) -> None:
    """The credential handed to the handler comes from the token, not the body."""
    token_workspace_id = uuid.uuid4()
    body_workspace_id = uuid.uuid4()
    credential = MacRelayCredential(
        workspace_id=token_workspace_id,
        phone_number_id=uuid.uuid4(),
    )
    mock_handle = AsyncMock(return_value={"status": "ok"})
    payload = {
        "event_id": "evt-1",
        "is_from_me": True,
        # Attacker-controlled fields; they must not influence the tenancy.
        "workspace_id": str(body_workspace_id),
        "to": "+19995550000",
    }

    with (
        _patch_relay_auth(credential=credential, configured=True),
        patch.object(mac_relay_module, "handle_mac_relay_message", mock_handle),
    ):
        response = await client.post(
            "/webhooks/mac-relay/messages",
            json=payload,
            headers={"Authorization": "Bearer macrelay_valid"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_handle.assert_awaited_once()
    assert mock_handle.await_args.args[0] == payload
    passed_credential = mock_handle.await_args.args[2]
    assert passed_credential is credential
    assert passed_credential.workspace_id == token_workspace_id


async def test_legacy_global_token_does_not_authenticate_by_default(client: AsyncClient) -> None:
    """The pre-H-4 shared token is dead unless the escape hatch is turned on."""
    with (
        _patch_relay_auth(credential=None, configured=True),
        patch.object(app_settings, "mac_relay_webhook_token", "shared-global-token"),
        patch.object(app_settings, "mac_relay_allow_legacy_global_token", False),
    ):
        response = await client.post(
            "/webhooks/mac-relay/messages",
            json={"event_id": "evt-1"},
            headers={"Authorization": "Bearer shared-global-token"},
        )

    assert response.status_code == 401


async def test_legacy_global_token_authenticates_unscoped_when_enabled(
    client: AsyncClient,
) -> None:
    """With the hatch on, the shared token yields an explicitly un-scoped credential."""
    mock_handle = AsyncMock(return_value={"status": "ok"})

    with (
        _patch_relay_auth(credential=None, configured=True),
        patch.object(app_settings, "mac_relay_webhook_token", "shared-global-token"),
        patch.object(app_settings, "mac_relay_allow_legacy_global_token", True),
        patch.object(mac_relay_module, "handle_mac_relay_message", mock_handle),
    ):
        response = await client.post(
            "/webhooks/mac-relay/messages",
            json={"event_id": "evt-1", "is_from_me": True},
            headers={"Authorization": "Bearer shared-global-token"},
        )

    assert response.status_code == 200
    credential = mock_handle.await_args.args[2]
    assert credential.workspace_id is None
    assert credential.is_legacy_global is True


async def test_handler_http_exception_is_not_laundered_into_500(client: AsyncClient) -> None:
    """Tenancy 404s are the answer; the catch-all must not swallow them."""
    credential = MacRelayCredential(workspace_id=uuid.uuid4())
    mock_handle = AsyncMock(side_effect=HTTPException(status_code=404, detail="nope"))

    with (
        _patch_relay_auth(credential=credential, configured=True),
        patch.object(mac_relay_module, "handle_mac_relay_message", mock_handle),
    ):
        response = await client.post(
            "/webhooks/mac-relay/messages",
            json={"event_id": "evt-1"},
            headers={"Authorization": "Bearer macrelay_valid"},
        )

    assert response.status_code == 404


async def test_unexpected_handler_error_returns_500(client: AsyncClient) -> None:
    credential = MacRelayCredential(workspace_id=uuid.uuid4())
    mock_handle = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        _patch_relay_auth(credential=credential, configured=True),
        patch.object(mac_relay_module, "handle_mac_relay_message", mock_handle),
    ):
        response = await client.post(
            "/webhooks/mac-relay/messages",
            json={"event_id": "evt-1"},
            headers={"Authorization": "Bearer macrelay_valid"},
        )

    assert response.status_code == 500


# ─── Handler: tenancy scoping ────────────────────────────────────────────────


async def test_credential_cannot_write_against_another_workspaces_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The security property H-4 exists for: workspace A's relay, workspace B's number.

    The fake session honours the query's workspace filter exactly as Postgres
    would, so this fails the moment ``_find_workspace_phone`` stops scoping.
    """
    workspace_a = uuid.uuid4()  # who the token authenticates as
    workspace_b = uuid.uuid4()  # who actually owns +12125550101

    victim_phone = MagicMock()
    victim_phone.phone_number = "+12125550101"
    victim_phone.workspace_id = workspace_b
    victim_phone.mac_relay_sender_id = None

    db = _WorkspaceScopedDb(phone_record=victim_phone, owner_workspace_id=workspace_b)
    _patch_session_local(monkeypatch, db)

    process_pipeline = AsyncMock()
    monkeypatch.setattr(handlers, "process_inbound_text_event", process_pipeline)

    with pytest.raises(HTTPException) as excinfo:
        await handlers.handle_mac_relay_message(
            {
                "guid": "relay-guid-1",
                "from": "+14155552671",
                "to": "+12125550101",
                "text": "hello",
                "is_from_me": False,
            },
            _make_log(),
            MacRelayCredential(workspace_id=workspace_a),
        )

    assert excinfo.value.status_code == 404
    # No lookup past the rejected one, and above all no write.
    process_pipeline.assert_not_awaited()
    assert len(db.executed) == 1
    assert db.executed[0].params.get("workspace_id_1") == workspace_a


async def test_find_workspace_phone_is_workspace_filtered() -> None:
    """The number lookup itself carries the tenant filter."""
    workspace_id = uuid.uuid4()
    db = _WorkspaceScopedDb(phone_record=None, owner_workspace_id=workspace_id)

    await handlers._find_workspace_phone(db, "+12125550101", workspace_id)

    compiled = db.executed[0]
    assert "phone_numbers.workspace_id" in str(compiled)
    assert compiled.params.get("workspace_id_1") == workspace_id


async def test_operator_check_is_pinned_to_the_credential_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relay cannot make us look up an operator in someone else's workspace."""
    credential_workspace_id = uuid.uuid4()
    other_workspace_id = uuid.uuid4()

    check_operator = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "check_operator_by_phone", check_operator)

    credential = MacRelayCredential(workspace_id=credential_workspace_id)
    checker = handlers._operator_checker_for(credential)
    assert checker is not None

    db = MagicMock()
    await checker(db, "+14155552671", other_workspace_id)

    assert check_operator.await_args.args[2] == credential_workspace_id


async def test_legacy_credential_falls_back_to_body_derived_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The un-scoped token has no tenant to pin to, so the old path stands."""
    assert handlers._operator_checker_for(MacRelayCredential(workspace_id=None)) is None

    phone_record = MagicMock()
    phone_record.phone_number = "+12125550101"
    phone_record.workspace_id = uuid.uuid4()
    phone_record.mac_relay_sender_id = None

    db = _make_db(execute_returns=[_Result(scalar=None)])
    _patch_session_local(monkeypatch, db)

    result = await handlers.handle_mac_relay_message(
        {
            "guid": "relay-guid-1",
            "from": "+14155552671",
            "to": "+12125550101",
            "text": "hello",
            "is_from_me": False,
        },
        _make_log(),
        MacRelayCredential(workspace_id=None),
    )

    # Legacy: an unknown number is ignored rather than treated as a tenancy breach.
    assert result == {"status": "ignored", "reason": "phone_number_not_found"}


# ─── Handler: existing behaviour ─────────────────────────────────────────────


async def test_handler_ignores_outbound_echo() -> None:
    log = _make_log()
    result = await handlers.handle_mac_relay_message(
        {"event_id": "evt-1", "is_from_me": True},
        log,
        MacRelayCredential(workspace_id=uuid.uuid4()),
    )

    assert result == {"status": "ignored", "reason": "outbound_echo"}


async def test_process_inbound_mac_relay_message_prefixes_provider_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = MagicMock(spec=Message)
    expected.provider_message_id = "mac-relay:relay-guid-1"
    expected.channel = MessageChannel.IMESSAGE

    persist = AsyncMock(return_value=InboundMessageIngestResult(expected, created=True))
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
        MacRelayCredential(workspace_id=workspace_id),
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

    captured: dict[str, Any] = {}

    async def fake_process_inbound_text_event(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
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
        MacRelayCredential(workspace_id=workspace_id),
    )

    captured_event = captured["event"]
    assert result["status"] == "ok"
    assert captured_event.provider_message_id == "mac-relay:relay-guid-1"
    assert captured_event.from_number == "+14155552671"
    assert captured_event.to_number == "+12125550101"
    assert captured_event.body == "hello"
    assert captured_event.workspace_id == workspace_id
    assert captured_event.channel == MessageChannel.IMESSAGE
    # Operator identification never runs against the body-supplied tenant.
    assert captured["check_operator_fn"] is not None


# ─── Helpers ─────────────────────────────────────────────────────────────────


class _Result:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _WorkspaceScopedDb:
    """Fake session that enforces a query's ``workspace_id`` filter.

    Returns the seeded row only when the query is scoped to the workspace that
    actually owns it — the behaviour a real database provides, so a lookup that
    drops its tenant filter is caught here instead of in production.
    """

    def __init__(self, phone_record: Any, owner_workspace_id: uuid.UUID) -> None:
        self._phone_record = phone_record
        self._owner_workspace_id = owner_workspace_id
        self.executed: list[Any] = []

    async def execute(self, query: Any) -> _Result:
        compiled = query.compile()
        self.executed.append(compiled)
        scoped_to = compiled.params.get("workspace_id_1")
        if scoped_to != self._owner_workspace_id:
            return _Result(scalar=None)
        return _Result(scalar=self._phone_record)


def _make_db(execute_returns: list[Any]) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(execute_returns))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _patch_session_local(monkeypatch: pytest.MonkeyPatch, db: Any) -> None:
    class _CM:
        async def __aenter__(self) -> Any:  # noqa: N805
            return db

        async def __aexit__(self, *exc: Any) -> None:  # noqa: N805
            return None

    monkeypatch.setattr(handlers, "AsyncSessionLocal", lambda: _CM())


@contextmanager
def _patch_relay_auth(
    *,
    credential: MacRelayCredential | None,
    configured: bool,
) -> Iterator[dict[str, AsyncMock]]:
    """Stub the route's token resolution so these stay unit-level.

    The legacy hatch is forced off here so a developer's local ``.env`` cannot
    quietly turn these assertions into a different test.
    """
    resolve = AsyncMock(return_value=credential)
    is_configured = AsyncMock(return_value=configured)

    class _CM:
        async def __aenter__(self) -> Any:  # noqa: N805
            return MagicMock()

        async def __aexit__(self, *exc: Any) -> None:  # noqa: N805
            return None

    with (
        patch.object(mac_relay_module, "AsyncSessionLocal", lambda: _CM()),
        patch.object(mac_relay_module, "resolve_mac_relay_credential", resolve),
        patch.object(mac_relay_module, "mac_relay_credentials_configured", is_configured),
        patch.object(app_settings, "mac_relay_allow_legacy_global_token", False),
    ):
        yield {"resolve": resolve, "configured": is_configured}


def _make_log() -> MagicMock:
    log = MagicMock()
    log.bind = MagicMock(return_value=log)
    return log
