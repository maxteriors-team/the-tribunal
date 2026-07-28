"""The voice bridge must reject unauthorized peers before accepting the socket.

``/voice/stream/{call_id}`` streams live customer call audio and runs against a
tenant's own AI credentials. These tests pin the handshake boundary: an
unauthorized connection must be closed *before* ``accept()``, so it never
reaches the call-context lookup or a provider session.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.services.telephony.stream_auth import STREAM_TOKEN_PARAM, mint_stream_token
from app.websockets.voice_bridge import router

CALL_ID = "v3:abc123-call-control-id"


@pytest.fixture
def client() -> TestClient:
    """Mount only the voice bridge router — no DB or provider dependencies."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _connect(client: TestClient, query: str) -> None:
    with client.websocket_connect(f"/voice/stream/{CALL_ID}{query}"):
        pass  # pragma: no cover - reaching here means the socket was accepted


def test_connection_without_a_ticket_is_rejected(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        _connect(client, "")


def test_connection_with_a_garbage_ticket_is_rejected(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        _connect(client, f"?{STREAM_TOKEN_PARAM}=not-a-real-token")


def test_expired_ticket_is_rejected(client: TestClient) -> None:
    expired = mint_stream_token(CALL_ID, ttl_seconds=-1)
    with pytest.raises(WebSocketDisconnect):
        _connect(client, f"?{STREAM_TOKEN_PARAM}={expired}")


def test_ticket_minted_for_another_call_is_rejected(client: TestClient) -> None:
    """Knowing one call control ID must not grant access to a different call."""
    other = mint_stream_token("v3:a-different-call")
    with pytest.raises(WebSocketDisconnect):
        _connect(client, f"?{STREAM_TOKEN_PARAM}={other}")
