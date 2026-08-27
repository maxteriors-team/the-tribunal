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
async def test_invoice_payment_receipt_is_branded_transactional_and_itemized(
    fake_resend: _FakeResend,
) -> None:
    key = uuid.uuid4()
    sent = await email.send_invoice_payment_receipt(
        to_email="dana@example.com",
        customer_name="Dana <Homeowner>",
        business_name="Maxteriors Lighting",
        invoice_number="INV-000042",
        payment_amount=150.0,
        invoice_total=200.0,
        total_paid=200.0,
        currency="usd",
        paid_at=email.datetime(2026, 8, 21, 14, 30, tzinfo=email.UTC),
        idempotency_key=key,
        logo_url="https://cdn.example.com/logo.png",
        support_email="office@example.com",
        support_phone="248-877-4672",
        invoice_url="https://app.example/p/invoices/token",
        service_summary="Gutter cleaning × 2; Window wash <premium>",
    )

    assert sent is True
    call = fake_resend.Emails.send_async.await_args
    params = call.args[0]
    assert params["to"] == ["dana@example.com"]
    assert params["subject"] == ("Receipt for invoice INV-000042 from Maxteriors Lighting")
    assert "Dana &lt;Homeowner&gt;" in params["html"]
    assert "USD 150.00" in params["html"]
    assert "USD 200.00" in params["html"]
    assert "Paid in full" in params["html"]
    assert "Services provided" in params["html"]
    assert "248-877-4672 or office@example.com" in params["html"]
    assert "Gutter cleaning × 2; Window wash &lt;premium&gt;" in params["html"]
    assert "Gutter cleaning × 2; Window wash <premium>" in params["text"]
    assert "https://cdn.example.com/logo.png" in params["html"]
    assert "View invoice" in params["html"]
    assert "service details" in params["text"]
    assert "unsubscribe" not in params["html"].lower()
    assert call.args[1] == {"idempotency_key": str(key)}


@pytest.mark.asyncio
async def test_invoice_partial_payment_receipt_shows_remaining_balance(
    fake_resend: _FakeResend,
) -> None:
    sent = await email.send_invoice_payment_receipt(
        to_email="dana@example.com",
        customer_name="Dana",
        business_name="Maxteriors Lighting",
        invoice_number="INV-000043",
        payment_amount=500,
        invoice_total=2785,
        total_paid=500,
        balance_remaining=2285,
        currency="usd",
        paid_at=email.datetime(2026, 8, 21, 14, 30, tzinfo=email.UTC),
        idempotency_key=uuid.uuid4(),
        service_summary="Christmas light installation",
    )

    assert sent is True
    params = fake_resend.Emails.send_async.await_args.args[0]
    assert "Partial payment" in params["html"]
    assert "Balance remaining" in params["html"]
    assert "USD 2,285.00" in params["html"]
    assert "Paid in full" not in params["html"]
    assert "Christmas light installation" in params["text"]


@pytest.mark.asyncio
async def test_payment_receipt_includes_minimal_client_info_and_escapes_it(
    fake_resend: _FakeResend,
) -> None:
    sent = await email.send_payment_received_notification(
        to_email="office@example.com",
        workspace_name="Maxteriors Lighting",
        amount=250.0,
        currency="usd",
        description="Deposit on QUO-42",
        client_name="Kim <script>alert(1)</script>",
        client_email="kim@example.com",
        client_phone="+15869184195",
        quote_number="QUO-42",
    )

    assert sent is True
    params = fake_resend.Emails.send_async.await_args.args[0]
    html = params["html"]
    assert "Client" in html
    assert "Kim &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "kim@example.com" in html
    assert "+15869184195" in html
    assert "QUO-42" in html
    assert "payment provider remains the source of truth" in html
    assert "<script>alert(1)</script>" not in html
    assert "payment_intent" not in html


@pytest.mark.asyncio
async def test_quote_acceptance_receipt_is_transactional_and_itemized(
    fake_resend: _FakeResend,
) -> None:
    key = uuid.UUID(int=42)
    sent = await email.send_quote_acceptance_receipt(
        to_email="dana@example.com",
        customer_name="Dana <Homeowner>",
        business_name="Maxteriors Lighting",
        quote_number="QUO-000042",
        quote_title="Backyard lighting",
        total=4242.5,
        currency="usd",
        accepted_at=email.datetime(2026, 8, 13, 14, 30, tzinfo=email.UTC),
        idempotency_key=key,
        support_email="office@example.com",
        deposit_required=True,
        deposit_amount=2121.25,
        proposal_url="https://app.example/p/quotes/token",
    )

    assert sent is True
    call = fake_resend.Emails.send_async.await_args
    params = call.args[0]
    assert params["to"] == ["dana@example.com"]
    assert params["subject"] == "Receipt for accepted proposal QUO-000042"
    assert "Dana &lt;Homeowner&gt;" in params["html"]
    assert "USD 4,242.50" in params["html"]
    assert "USD 2,121.25 (due)" in params["html"]
    assert "View accepted proposal" in params["html"]
    assert "unsubscribe" not in params["html"].lower()
    assert call.args[1] == {"idempotency_key": str(key)}


@pytest.mark.asyncio
async def test_quote_email_renders_visible_and_plain_text_proposal_links(
    fake_resend: _FakeResend,
) -> None:
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
    assert "Button not showing?" in html
    assert "https://app.example.com/p/quotes/abc123token" in html
    assert "1,070.00 USD" in html
    assert "View your proposal:" in params["text"]
    assert "https://app.example.com/p/quotes/abc123token" in params["text"]
    # The caller-provided provider key is forwarded unchanged.
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


@pytest.mark.asyncio
async def test_campaign_email_makes_bare_url_clickable(fake_resend: _FakeResend) -> None:
    """A resource link the customer cannot tap reads exactly like a broken send.

    Mail clients do not reliably auto-link a bare URL inside an HTML part, and
    the campaign shell (unlike the shared ``email_layout`` renderer) did not
    link them at all — so a texted-and-emailed guide link arrived as dead text.
    """
    message_id = await email.send_campaign_email(
        to_email="customer@example.com",
        subject="Your lighting guide",
        body=(
            "Everything you need: https://go.example.com/static/guides/index.html\nText us anytime."
        ),
        unsubscribe_url="https://go.example.com/u/abc",
    )

    assert message_id == "email_123"
    html = fake_resend.Emails.send_async.await_args.args[0]["html"]
    assert '<a href="https://go.example.com/static/guides/index.html"' in html
    assert "Text us anytime." in html


@pytest.mark.asyncio
async def test_campaign_email_link_keeps_trailing_punctuation_out_of_href(
    fake_resend: _FakeResend,
) -> None:
    await email.send_campaign_email(
        to_email="customer@example.com",
        subject="Guide",
        body="Read it here: https://go.example.com/g.html.",
    )

    html = fake_resend.Emails.send_async.await_args.args[0]["html"]
    assert '<a href="https://go.example.com/g.html"' in html
    assert "g.html.</a>" not in html


@pytest.mark.asyncio
async def test_campaign_email_still_escapes_markup(fake_resend: _FakeResend) -> None:
    """Linkifying must not reopen the injection path it runs after."""
    await email.send_campaign_email(
        to_email="customer@example.com",
        subject="Guide",
        body="<img src=x onerror=alert(1)> https://go.example.com/a?b=1&c=2",
    )

    html = fake_resend.Emails.send_async.await_args.args[0]["html"]
    assert "<img" not in html
    assert "&lt;img" in html
    # Query separators stay escaped inside the href: valid HTML that the
    # browser decodes back to a single "&".
    assert '<a href="https://go.example.com/a?b=1&amp;c=2"' in html


@pytest.mark.asyncio
async def test_automation_email_carries_explicit_workspace_brand_logo(
    fake_resend: _FakeResend,
) -> None:
    """One workspace can opt into its logo without branding every tenant."""
    logo_url = "https://go.example.com/static/brand/maxteriors-logo.png"

    sent = await email.send_automation_email(
        to_email="customer@example.com",
        subject="Your new lighting",
        body="Here's how to run it: https://go.example.com/static/guides/index.html",
        category=email.EmailCategory.TRANSACTIONAL,
        business_name="Maxteriors",
        logo_url=logo_url,
    )

    assert sent is True
    html = fake_resend.Emails.send_async.await_args.args[0]["html"]
    assert f'src="{logo_url}"' in html, "brand logo must be in the header"
    assert 'alt="Maxteriors"' in html


@pytest.mark.parametrize(
    "logo_url",
    [
        "http://localhost:8000/static/logo.png",
        "https://localhost:8000/static/logo.png",
        "",
        "/static/logo.png",
    ],
)
def test_safe_logo_url_refuses_an_unusable_url(logo_url: str) -> None:
    """A mail client cannot fetch localhost or a relative path.

    Returning None makes the shell fall back to a readable text wordmark instead
    of putting a broken-image icon at the top of a customer's email.
    """
    assert email._safe_logo_url(logo_url) is None
    assert email._brand("Other Workspace", logo_url).logo_url is None


def test_brand_without_explicit_logo_does_not_leak_maxteriors_asset() -> None:
    """The app is multi-tenant; branding must come from the sending workspace."""
    assert email._brand("Other Workspace").logo_url is None


def test_safe_logo_url_accepts_absolute_https() -> None:
    logo_url = "https://go.example.com/static/brand/maxteriors-logo.png"

    assert email._safe_logo_url(logo_url) == logo_url


@pytest.mark.asyncio
async def test_appointment_reminder_linkifies_meeting_url(fake_resend: _FakeResend) -> None:
    meeting_url = "https://zoom.us/j/123456789"

    sent = await email.send_appointment_reminder_email(
        to_email="customer@example.com",
        contact_name="Dana Reyes",
        business_name="Sparkle Exteriors",
        body_text=f"Join Zoom: {meeting_url}",
        appointment_time=email.datetime(2026, 8, 20, 14, 30, tzinfo=email.UTC),
        timezone="America/New_York",
    )

    assert sent is True
    params = fake_resend.Emails.send_async.await_args.args[0]
    assert f'href="{meeting_url}"' in params["html"]
    assert params["html"].count(meeting_url) == 2


@pytest.mark.asyncio
async def test_anytime_appointment_reminder_omits_synthetic_noon(
    fake_resend: _FakeResend,
) -> None:
    sent = await email.send_appointment_reminder_email(
        to_email="customer@example.com",
        contact_name="Dana Reyes",
        business_name="Sparkle Exteriors",
        body_text="Your appointment is Thursday, August 20 at any time.",
        appointment_time=email.datetime(2026, 8, 20, 16, 0, tzinfo=email.UTC),
        timezone="America/New_York",
        anytime=True,
    )

    assert sent is True
    params = fake_resend.Emails.send_async.await_args.args[0]
    assert params["subject"] == "Reminder: your appointment Thursday, August 20 at any time"
    assert "Thursday, August 20 at any time &middot; Sparkle Exteriors" in params["html"]
    assert "12:00 PM" not in params["subject"]
    assert "12:00 PM" not in params["html"]
