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
        workspace_name="Acme Home Services",
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
    assert params["subject"] == "You've been invited to join Acme Home Services"
    assert "https://app.example/invitations/abc" in params["html"]
    fake_resend.Emails.send.assert_not_called()


@pytest.mark.asyncio
async def test_invitation_email_passes_resend_idempotency_key(fake_resend: _FakeResend) -> None:
    key = uuid.uuid4()

    sent = await email.send_invitation_email(
        to_email="agent@example.com",
        workspace_name="Acme Home Services",
        inviter_name="Nolan",
        invitation_url="https://app.example/invitations/abc",
        role="admin",
        idempotency_key=key,
    )

    assert sent is True
    fake_resend.Emails.send_async.assert_awaited_once()
    assert fake_resend.Emails.send_async.await_args.args[1] == {"idempotency_key": str(key)}


@pytest.mark.asyncio
async def test_invoice_email_renders_summary_and_pay_button(fake_resend: _FakeResend) -> None:
    key = uuid.uuid4()

    sent = await email.send_invoice_email(
        to_email="customer@example.com",
        workspace_name="Acme Plumbing",
        invoice_number="INV-000007",
        amount_str="250.00 USD",
        due_date="2026-07-15",
        pay_url="https://checkout.stripe.com/c/pay/cs_test_abc",
        notes="Thanks for your business",
        idempotency_key=key,
    )

    assert sent is True
    call = fake_resend.Emails.send_async.await_args
    assert call is not None
    params = call.args[0]
    assert params["to"] == ["customer@example.com"]
    assert params["subject"] == "Invoice INV-000007 from Acme Plumbing"
    html = params["html"]
    assert "250.00 USD" in html
    assert "2026-07-15" in html
    assert "https://checkout.stripe.com/c/pay/cs_test_abc" in html
    assert "Pay now" in html
    assert "Thanks for your business" in html
    # Idempotency key forwarded so a re-send of the same invoice is deduped.
    assert call.args[1] == {"idempotency_key": str(key)}


@pytest.mark.asyncio
async def test_invoice_email_omits_pay_button_without_url(fake_resend: _FakeResend) -> None:
    sent = await email.send_invoice_email(
        to_email="customer@example.com",
        workspace_name="Acme Plumbing",
        invoice_number="INV-000008",
        amount_str="99.00 USD",
        pay_url=None,
    )

    assert sent is True
    params = fake_resend.Emails.send_async.await_args.args[0]
    html = params["html"]
    assert "99.00 USD" in html
    assert "Pay now" not in html


@pytest.mark.asyncio
async def test_quote_email_renders_view_proposal_button(fake_resend: _FakeResend) -> None:
    key = uuid.uuid4()

    sent = await email.send_quote_email(
        to_email="client@example.com",
        workspace_name="Maxteriors Lighting",
        quote_number="QUO-000042",
        amount_str="1,070.00 USD",
        title="Backyard lighting install",
        expiry_date="2026-07-31",
        notes="Excited to work with you!",
        proposal_url="https://app.example.com/p/quotes/abc123token",
        idempotency_key=key,
    )

    assert sent is True
    call = fake_resend.Emails.send_async.await_args
    assert call is not None
    params = call.args[0]
    assert params["to"] == ["client@example.com"]
    assert params["subject"] == "Quote QUO-000042 from Maxteriors Lighting"
    html = params["html"]
    assert "View your proposal" in html
    assert "https://app.example.com/p/quotes/abc123token" in html
    assert "1,070.00 USD" in html
    # Idempotency key forwarded so a re-send of the same quote is deduped.
    assert call.args[1] == {"idempotency_key": str(key)}


@pytest.mark.asyncio
async def test_quote_email_omits_button_without_proposal_url(fake_resend: _FakeResend) -> None:
    sent = await email.send_quote_email(
        to_email="client@example.com",
        workspace_name="Maxteriors Lighting",
        quote_number="QUO-000043",
        amount_str="99.00 USD",
        proposal_url=None,
    )

    assert sent is True
    html = fake_resend.Emails.send_async.await_args.args[0]["html"]
    assert "99.00 USD" in html
    assert "View your proposal" not in html


@pytest.mark.asyncio
async def test_invoice_email_escapes_notes(fake_resend: _FakeResend) -> None:
    # Operator-authored notes must not be able to inject markup.
    sent = await email.send_invoice_email(
        to_email="customer@example.com",
        workspace_name="Acme",
        invoice_number="INV-1",
        amount_str="10.00 USD",
        notes="<script>alert(1)</script>",
    )

    assert sent is True
    html = fake_resend.Emails.send_async.await_args.args[0]["html"]
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
