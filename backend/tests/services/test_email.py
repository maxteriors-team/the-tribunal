"""Tests for async Resend email delivery helpers."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import email


class _FakeResendEmails:
    def __init__(self) -> None:
        self.send_async = AsyncMock(return_value={"id": "email_123"})
        self.send = AsyncMock()


class _FakeResend:
    def __init__(self) -> None:
        self.api_key: str | None = None
        self.Emails = _FakeResendEmails()


@pytest.fixture
def fake_resend(monkeypatch: pytest.MonkeyPatch) -> _FakeResend:
    client = _FakeResend()
    monkeypatch.setattr(email, "RESEND_AVAILABLE", True)
    monkeypatch.setattr(email, "resend", client)
    monkeypatch.setattr(email.settings, "resend_api_key", "resend-key")
    monkeypatch.setattr(email.settings, "resend_from_name", "Tribunal")
    monkeypatch.setattr(email.settings, "resend_from_email", "noreply@example.com")
    return client


@pytest.mark.asyncio
async def test_send_uses_resend_async_client(fake_resend: _FakeResend) -> None:
    result = await email._send(
        {
            "from": "Tribunal <noreply@example.com>",
            "to": ["lead@example.com"],
            "subject": "Hello",
            "html": "<p>Hello</p>",
        }
    )

    assert result == {"id": "email_123"}
    assert fake_resend.api_key == "resend-key"
    fake_resend.Emails.send_async.assert_awaited_once_with(
        {
            "from": "Tribunal <noreply@example.com>",
            "to": ["lead@example.com"],
            "subject": "Hello",
            "html": "<p>Hello</p>",
        },
        None,
    )
    fake_resend.Emails.send.assert_not_called()


@pytest.mark.asyncio
async def test_send_returns_none_when_resend_async_client_fails(
    fake_resend: _FakeResend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = MagicMock()
    fake_resend.Emails.send_async.side_effect = RuntimeError("network down")
    monkeypatch.setattr(email, "logger", logger)

    result = await email._send({"to": ["lead@example.com"]})

    assert result is None
    fake_resend.Emails.send_async.assert_awaited_once_with({"to": ["lead@example.com"]}, None)
    logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_invitation_email_uses_async_resend_path(fake_resend: _FakeResend) -> None:
    sent = await email.send_invitation_email(
        to_email="agent@example.com",
        workspace_name="Acme Realty",
        inviter_name="Nolan",
        invitation_url="https://app.example/invitations/abc",
        role="admin",
    )

    assert sent is True
    call = fake_resend.Emails.send_async.await_args
    assert call is not None
    args: tuple[dict[str, Any], ...] = call.args
    params = args[0]
    assert params["from"] == "Tribunal <noreply@example.com>"
    assert params["to"] == ["agent@example.com"]
    assert params["subject"] == "You've been invited to join Acme Realty"
    assert "https://app.example/invitations/abc" in params["html"]
    fake_resend.Emails.send.assert_not_called()


@pytest.mark.asyncio
async def test_invitation_email_passes_resend_idempotency_key(fake_resend: _FakeResend) -> None:
    key = uuid.uuid4()

    sent = await email.send_invitation_email(
        to_email="agent@example.com",
        workspace_name="Acme Realty",
        inviter_name="Nolan",
        invitation_url="https://app.example/invitations/abc",
        role="admin",
        idempotency_key=key,
    )

    assert sent is True
    fake_resend.Emails.send_async.assert_awaited_once()
    assert fake_resend.Emails.send_async.await_args.args[1] == {"idempotency_key": str(key)}
