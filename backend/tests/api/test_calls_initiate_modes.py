"""Contract for ``POST /workspaces/{id}/calls`` mode selection.

Two failure modes this pins down:

- **Dead air.** An ``mode="ai"`` call with no resolvable agent used to dial the
  contact and then start no audio stream, so the customer answered to silence.
  The request is now rejected instead.
- **Toll fraud.** ``mode="user"`` rings a number we pay for, so a free-form
  ``user_phone_number`` would let any comms-send member bill the workspace for
  calls to arbitrary destinations. Only allowlisted numbers are accepted.

The happy path proves the *rep* is dialed first (never the contact), which is
the whole point of user mode.

DB-free via dependency overrides plus a fake session that assigns primary keys
on flush the way a real INSERT would.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import calls as calls_module
from app.core.config import settings as app_settings
from app.services.telephony.telnyx_voice import TelnyxVoiceService
from app.services.telephony.telnyx_webrtc import BrowserCredential

WS_ID = uuid.uuid4()
BASE = f"/api/v1/workspaces/{WS_ID}/calls"

WORKSPACE_NUMBER = "+12125550100"
CONTACT_NUMBER = "+14155552672"
USER_NUMBER = "+13105550143"
OFF_ALLOWLIST_NUMBER = "+12125550188"


class _Scalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def first(self) -> Any:
        return self._values[0] if self._values else None

    def all(self) -> list[Any]:
        return list(self._values)


class _Result:
    """Minimal stand-in for a SQLAlchemy ``Result``."""

    def __init__(self, *, scalar: Any = None, values: list[Any] | None = None) -> None:
        self._scalar = scalar
        self._values = values if values is not None else ([scalar] if scalar is not None else [])

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)


class _FakeSession:
    """Async-session shape: canned ``execute`` results, real flush semantics."""

    def __init__(self, results: list[_Result]) -> None:
        self._results = list(results)
        self.added: list[Any] = []
        self.executed = 0

    async def execute(self, *_args: Any, **_kwargs: Any) -> _Result:
        self.executed += 1
        if not self._results:
            return _Result()
        return self._results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        # A real INSERT applies the column defaults; the code under test reads
        # ``message.id`` straight afterwards.
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)

    async def commit(self) -> None:
        await self.flush()

    async def refresh(self, _obj: Any) -> None:
        return None

    async def get(self, _model: Any, _pk: Any) -> Any:
        return None


def _phone_record() -> MagicMock:
    record = MagicMock()
    record.id = uuid.uuid4()
    record.phone_number = WORKSPACE_NUMBER
    record.voice_enabled = True
    record.assigned_agent_id = None
    return record


@asynccontextmanager
async def _test_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _build_app(db: _FakeSession, *, user_phone: str | None, ws_settings: dict[str, Any]) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[_FakeSession]:
        yield db

    async def override_get_workspace() -> MagicMock:
        ws = MagicMock()
        ws.id = WS_ID
        ws.is_active = True
        ws.settings = ws_settings
        return ws

    async def override_get_current_user() -> MagicMock:
        user = MagicMock()
        user.id = 1
        user.is_active = True
        user.phone_number = user_phone
        user.telnyx_telephony_credential_id = None
        user.telnyx_sip_username = None
        return user

    async def override_get_membership() -> MagicMock:
        membership = MagicMock()
        membership.user_id = 1
        membership.workspace_id = WS_ID
        membership.role = "owner"
        return membership

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_membership] = override_get_membership
    app.include_router(calls_module.router, prefix="/api/v1/workspaces/{workspace_id}/calls")
    return app


@asynccontextmanager
async def _client(
    db: _FakeSession,
    *,
    user_phone: str | None = USER_NUMBER,
    ws_settings: dict[str, Any] | None = None,
) -> AsyncIterator[AsyncClient]:
    app = _build_app(db, user_phone=user_phone, ws_settings=ws_settings or {})
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def _telnyx_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "telnyx_api_key", "test-key")
    monkeypatch.setattr(app_settings, "telnyx_connection_id", "conn-123")
    monkeypatch.setattr(
        app_settings, "telnyx_webrtc_connection_id", "10000000-0000-4000-8000-000000000001"
    )
    monkeypatch.setattr(app_settings, "api_base_url", "https://api.example.com")


# --------------------------------------------------------------------------- #
# mode="ai"
# --------------------------------------------------------------------------- #


async def test_ai_mode_without_resolvable_agent_is_rejected() -> None:
    """No conversation agent, no number agent, no workspace agent -> 400."""
    db = _FakeSession(
        [
            _Result(scalar=_phone_record()),  # from_phone_number lookup
            _Result(),  # conversation assigned_agent_id
            _Result(),  # workspace voice-agent fallback
        ]
    )
    async with _client(db) as client:
        resp = await client.post(
            BASE,
            json={"to_number": CONTACT_NUMBER, "from_phone_number": WORKSPACE_NUMBER},
        )

    assert resp.status_code == 400, resp.text
    assert "voice agent" in resp.json()["detail"]


async def test_ai_mode_falls_back_to_workspace_voice_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolvable agent is passed to the dialer even when none was requested."""
    agent_id = uuid.uuid4()
    db = _FakeSession(
        [
            _Result(scalar=_phone_record()),
            _Result(),  # no conversation agent
            _Result(scalar=agent_id),  # workspace fallback agent
        ]
    )

    message = MagicMock()
    message.id = uuid.uuid4()
    message.conversation_id = uuid.uuid4()
    message.direction = "outbound"
    message.channel = "voice"
    message.status = "ringing"
    message.duration_seconds = None
    message.recording_url = None
    message.transcript = None
    message.created_at = datetime.now(UTC)
    message.agent_id = agent_id
    message.is_ai = True

    initiate = AsyncMock(return_value=message)
    monkeypatch.setattr(TelnyxVoiceService, "initiate_call", initiate)

    async with _client(db) as client:
        resp = await client.post(
            BASE,
            json={"to_number": CONTACT_NUMBER, "from_phone_number": WORKSPACE_NUMBER},
        )

    assert resp.status_code == 201, resp.text
    assert initiate.await_args.kwargs["agent_id"] == agent_id
    assert resp.json()["is_ai"] is True


# --------------------------------------------------------------------------- #
# mode="user"
# --------------------------------------------------------------------------- #


async def test_user_mode_rejects_off_allowlist_callback_number() -> None:
    """An arbitrary E.164 would let a member bill the workspace for any dial."""
    db = _FakeSession(
        [
            _Result(scalar=_phone_record()),  # from_phone_number lookup
            _Result(values=[WORKSPACE_NUMBER]),  # workspace-owned voice numbers
        ]
    )
    async with _client(db) as client:
        resp = await client.post(
            BASE,
            json={
                "to_number": CONTACT_NUMBER,
                "from_phone_number": WORKSPACE_NUMBER,
                "mode": "user",
                "user_phone_number": OFF_ALLOWLIST_NUMBER,
            },
        )

    assert resp.status_code == 400, resp.text
    assert "not allowed" in resp.json()["detail"]


async def test_user_mode_rejects_when_no_callback_number_configured() -> None:
    """No profile phone, no transfer destination, no workspace number -> 400."""
    db = _FakeSession(
        [
            _Result(scalar=_phone_record()),
            _Result(values=[]),
        ]
    )
    async with _client(db, user_phone=None) as client:
        resp = await client.post(
            BASE,
            json={
                "to_number": CONTACT_NUMBER,
                "from_phone_number": WORKSPACE_NUMBER,
                "mode": "user",
            },
        )

    assert resp.status_code == 400, resp.text
    assert "callback number" in resp.json()["detail"]


async def test_user_mode_dials_the_rep_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: rep leg is dialed, contact is not, and the call is not AI."""
    db = _FakeSession(
        [
            _Result(scalar=_phone_record()),  # from_phone_number lookup
            _Result(values=[WORKSPACE_NUMBER]),  # allowlist: workspace numbers
            _Result(),  # conversation lookup (none yet)
            _Result(),  # contact lookup (none)
        ]
    )

    dial = AsyncMock(return_value="v3:rep-leg-ccid")
    monkeypatch.setattr(TelnyxVoiceService, "dial_transfer_leg", dial)
    stored: list[Any] = []

    async def _capture(pending: Any) -> None:
        stored.append(pending)

    monkeypatch.setattr(
        "app.services.telephony.user_call.store_pending_user_call",
        _capture,
    )

    async with _client(db) as client:
        resp = await client.post(
            BASE,
            json={
                "to_number": CONTACT_NUMBER,
                "from_phone_number": WORKSPACE_NUMBER,
                "mode": "user",
                "user_phone_number": USER_NUMBER,
            },
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["is_ai"] is False
    assert body["agent_id"] is None

    # The single dial went to the rep — the contact is only dialed after the
    # rep answers, from the webhook handler.
    dial.assert_awaited_once()
    assert dial.await_args.kwargs["to_number"] == USER_NUMBER
    assert dial.await_args.kwargs["from_number"] == WORKSPACE_NUMBER
    assert dial.await_args.kwargs["timeout_secs"] == 25

    message = next(obj for obj in db.added if obj.__class__.__name__ == "Message")
    assert message.is_ai is False
    assert message.agent_id is None
    assert message.provider_message_id == "v3:rep-leg-ccid"
    assert message.status == "ringing"

    assert len(stored) == 1
    assert stored[0].rep_call_control_id == "v3:rep-leg-ccid"
    assert stored[0].contact_call_control_id is None
    assert stored[0].contact_number == CONTACT_NUMBER


# --------------------------------------------------------------------------- #
# mode="browser"
# --------------------------------------------------------------------------- #


async def test_browser_mode_dials_only_server_owned_sip_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client cannot choose a paid callback or arbitrary SIP destination."""
    db = _FakeSession(
        [
            _Result(scalar=_phone_record()),
            _Result(),  # conversation lookup (none yet)
            _Result(),  # contact lookup (none)
        ]
    )

    credential = BrowserCredential(
        credential_id="20000000-0000-4000-8000-000000000002",
        sip_username="provider-issued-user",
    )
    browser_service = MagicMock()
    browser_service.ensure_user_credential = AsyncMock(return_value=credential)
    browser_service.close = AsyncMock()
    monkeypatch.setattr(
        calls_module, "TelnyxWebRTCService", MagicMock(return_value=browser_service)
    )
    monkeypatch.setattr(calls_module, "enforce_softphone_call_limits", AsyncMock(return_value=None))

    dial_browser = AsyncMock(return_value="v3:browser-leg-ccid")
    dial_phone = AsyncMock()
    monkeypatch.setattr(TelnyxVoiceService, "dial_browser_leg", dial_browser)
    monkeypatch.setattr(TelnyxVoiceService, "dial_transfer_leg", dial_phone)
    monkeypatch.setattr(
        "app.services.telephony.user_call.store_pending_user_call",
        AsyncMock(return_value=None),
    )

    async with _client(db) as client:
        resp = await client.post(
            BASE,
            json={
                "to_number": CONTACT_NUMBER,
                "from_phone_number": WORKSPACE_NUMBER,
                "mode": "browser",
                "user_phone_number": OFF_ALLOWLIST_NUMBER,
            },
        )

    assert resp.status_code == 201, resp.text
    assert resp.json()["is_ai"] is False
    dial_phone.assert_not_awaited()
    dial_browser.assert_awaited_once()
    assert dial_browser.await_args.kwargs["sip_username"] == "provider-issued-user"


async def test_webrtc_token_is_memory_only_and_not_cacheable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeSession([])
    browser_service = MagicMock()
    browser_service.issue_user_token = AsyncMock(return_value="header.payload.signature")
    browser_service.close = AsyncMock()
    monkeypatch.setattr(
        calls_module, "TelnyxWebRTCService", MagicMock(return_value=browser_service)
    )
    monkeypatch.setattr(calls_module, "enforce_softphone_token_limit", AsyncMock(return_value=None))

    async with _client(db) as client:
        resp = await client.post(f"{BASE}/webrtc/token")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"token": "header.payload.signature"}
    assert resp.headers["cache-control"] == "no-store"
    browser_service.issue_user_token.assert_awaited_once()
    browser_service.close.assert_awaited_once()
