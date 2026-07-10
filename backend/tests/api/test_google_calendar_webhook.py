"""Wiring tests for the Google Calendar push webhook (DB-free paths)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.webhooks import google_calendar as gc_webhook


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(gc_webhook.router, prefix="/webhooks/google-calendar")
    return TestClient(app)


def test_sync_handshake_returns_ok() -> None:
    client = _client()
    resp = client.post(
        "/webhooks/google-calendar/notifications",
        headers={"X-Goog-Resource-State": "sync", "X-Goog-Channel-ID": "chan"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_missing_channel_is_ignored() -> None:
    client = _client()
    resp = client.post(
        "/webhooks/google-calendar/notifications",
        headers={"X-Goog-Resource-State": "exists"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}
