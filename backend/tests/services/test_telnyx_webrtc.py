"""Provider-boundary tests for memory-only browser credentials."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from app.models.user import User
from app.services.telephony.telnyx_voice import TelnyxVoiceService
from app.services.telephony.telnyx_webrtc import TelnyxWebRTCService

CONNECTION_ID = "1293384261075731499"
CREDENTIAL_ID = "20000000-0000-4000-8000-000000000002"


class _Result:
    def __init__(self, user: User) -> None:
        self.user = user

    def scalar_one_or_none(self) -> User:
        return self.user


class _Session:
    def __init__(self, user: User) -> None:
        self.user = user
        self.commits = 0

    async def execute(self, *_args: Any, **_kwargs: Any) -> _Result:
        return _Result(self.user)

    async def commit(self) -> None:
        self.commits += 1


async def test_issue_token_stores_identity_but_never_password_or_jwt() -> None:
    user = User(email="operator@example.com", hashed_password="hash", is_active=True)
    user.id = 42
    session = _Session(user)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/telephony_credentials":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": CREDENTIAL_ID,
                        "sip_username": "provider-user-42",
                        "sip_password": "must-not-be-stored",
                    }
                },
            )
        if request.url.path == f"/v2/telephony_credentials/{CREDENTIAL_ID}/token":
            return httpx.Response(200, text="header.payload.signature")
        return httpx.Response(404)

    client = httpx.AsyncClient(
        base_url="https://api.telnyx.com/v2", transport=httpx.MockTransport(handler)
    )
    service = TelnyxWebRTCService("secret-api-key", CONNECTION_ID, client=client)
    try:
        token = await service.issue_user_token(session, user)  # type: ignore[arg-type]
    finally:
        await client.aclose()

    assert token == "header.payload.signature"
    assert user.telnyx_telephony_credential_id == CREDENTIAL_ID
    assert user.telnyx_sip_username == "provider-user-42"
    assert session.commits == 1
    assert not hasattr(user, "telnyx_sip_password")
    assert all("secret-api-key" not in request.content.decode() for request in requests)
    create_payload = json.loads(requests[0].content)
    assert create_payload == {
        "connection_id": CONNECTION_ID,
        "name": "tribunal-user-42",
        "tag": "tribunal-browser",
    }


async def test_browser_leg_uses_fixed_internal_sip_domain() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(201, json={"data": {"call_control_id": "v3:browser-leg"}})

    service = TelnyxVoiceService("secret-api-key")
    service._client = httpx.AsyncClient(  # noqa: SLF001 - inject provider transport
        base_url="https://api.telnyx.com/v2", transport=httpx.MockTransport(handler)
    )
    try:
        call_id = await service.dial_browser_leg(
            sip_username="provider-user-42",
            from_number="+12125550100",
            connection_id=CONNECTION_ID,
            webhook_url="https://api.example.com/webhooks/telnyx/voice",
            client_state="encoded-state",
            command_id="browser-rep-message-id",
        )
        rejected = await service.dial_browser_leg(
            sip_username="attacker@example.com",
            from_number="+12125550100",
            connection_id=CONNECTION_ID,
            webhook_url="https://api.example.com/webhooks/telnyx/voice",
            client_state="encoded-state",
            command_id="bad",
        )
    finally:
        await service.close()

    assert call_id == "v3:browser-leg"
    assert rejected is None
    assert len(captured) == 1
    assert captured[0]["to"] == "sip:provider-user-42@telnyx.com"
    assert captured[0]["connection_id"] == CONNECTION_ID


async def test_deleted_provider_credential_is_recreated_once() -> None:
    user = User(email="operator@example.com", hashed_password="hash", is_active=True)
    user.id = 42
    user.telnyx_telephony_credential_id = str(uuid.uuid4())
    user.telnyx_sip_username = "stale-user"
    session = _Session(user)
    token_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_attempts
        if request.url.path.endswith("/token"):
            token_attempts += 1
            if token_attempts == 1:
                return httpx.Response(404)
            return httpx.Response(200, text="new.header.signature")
        return httpx.Response(
            201,
            json={"data": {"id": CREDENTIAL_ID, "sip_username": "replacement-user"}},
        )

    client = httpx.AsyncClient(
        base_url="https://api.telnyx.com/v2", transport=httpx.MockTransport(handler)
    )
    service = TelnyxWebRTCService("secret-api-key", CONNECTION_ID, client=client)
    try:
        token = await service.issue_user_token(session, user)  # type: ignore[arg-type]
    finally:
        await client.aclose()

    assert token == "new.header.signature"
    assert user.telnyx_telephony_credential_id == CREDENTIAL_ID
    assert user.telnyx_sip_username == "replacement-user"
    assert session.commits == 2
    assert token_attempts == 2
