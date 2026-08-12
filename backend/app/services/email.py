"""Email service for sending transactional emails via Resend."""

import uuid
from datetime import UTC, datetime
from html import escape as html_escape
from typing import TYPE_CHECKING, Any, Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from app.core.config import settings

try:
    import resend

    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    if TYPE_CHECKING:
        import resend

logger = structlog.get_logger()


class _ResendEmails(Protocol):
    async def send_async(
        self,
        params: dict[str, Any],
        options: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send one email with Resend's async HTTP client."""


class _ResendModule(Protocol):
    api_key: str | None
    Emails: _ResendEmails


def _from_address() -> str:
    name = settings.resend_from_name or "Maxteriors"
    email = settings.resend_from_email or "noreply@example.com"
    return f"{name} <{email}>"


DEFAULT_DISPLAY_TIMEZONE = "America/New_York"


def format_local_datetime(value: datetime, timezone: str | None = None) -> str:
    """Render a datetime in the workspace's zone, e.g. "Monday, August 10 at 2:00 PM EDT".

    Appointment rows are stored as UTC-normalised ``timestamptz``. Formatting one
    without converting shows the operator a UTC wall-clock labelled as their
    local time — a silently wrong appointment time in every notification. Naive
    values are assumed UTC, matching what the DB hands back.
    """
    try:
        tz = ZoneInfo(timezone or DEFAULT_DISPLAY_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo(DEFAULT_DISPLAY_TIMEZONE)

    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    local = aware.astimezone(tz)
    label = local.strftime("%Z") or timezone or ""
    return f"{local.strftime('%A, %B %-d at %-I:%M %p')} {label}".strip()


async def _send(
    params: dict[str, Any],
    *,
    idempotency_key: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """Send an email via Resend, returning the response dict or None on failure."""
    if not RESEND_AVAILABLE:
        logger.warning("resend_not_installed", hint="Install with: uv add resend")
        return None

    if not settings.resend_api_key:
        logger.warning("resend_api_key_not_configured")
        return None

    resend_module = cast(_ResendModule, resend)
    resend_module.api_key = settings.resend_api_key
    options = {"idempotency_key": str(idempotency_key)} if idempotency_key else None
    try:
        response = await resend_module.Emails.send_async(params, options)
    except Exception as exc:
        logger.error("resend_send_failed", error=str(exc), to=params.get("to"))
        return None
    return dict(response) if response else {}


def _text_to_html(body: str) -> str:
    """Wrap plain automation copy in a minimal, safe HTML email shell.

    The body is operator-authored template output; escape it so it cannot
    inject markup, then preserve line breaks as paragraph spacing.
    """
    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    safe_body = html_escape(body).replace("\n", "<br>")
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <p>{safe_body}</p>
</body>
</html>"""


async def send_event_notification_email(
    to_email: str,
    subject: str,
    heading: str,
    intro: str,
    details: dict[str, str] | None = None,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Email an operator about a new actionable workspace event.

    Generic transactional template shared by the actionable-event notifications
    (reviews, at-risk deals, missed-call text-backs, roleplay runs, automation
    triggers). ``intro`` and the ``details`` label/value pairs are all
    operator/contact-derived free text and are HTML-escaped here so they can
    never inject markup. Returns True only when the provider accepted the send.
    """
    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    label_style = "color: #666; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;"
    value_style = "font-size: 16px; font-weight: 600; color: #1a1a1a; margin: 2px 0 16px 0;"

    detail_rows = ""
    if details:
        rows = []
        for label, value in details.items():
            rows.append(
                f'<p style="{label_style}">{html_escape(label)}</p>'
                f'<p style="{value_style}">{html_escape(value)}</p>'
            )
        detail_rows = (
            '<div style="background-color: #f8f9fa; padding: 20px; '
            'border-radius: 8px; margin: 24px 0;">' + "".join(rows) + "</div>"
        )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1a1a1a; margin-bottom: 5px;">{html_escape(heading)}</h1>
    </div>
    <p>{html_escape(intro)}</p>
    {detail_rows}
    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
    <p style="color: #999; font-size: 12px; text-align: center;">
        Sent by Maxteriors
    </p>
</body>
</html>"""

    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "event_notification_email_sent",
        to_email=to_email,
        subject=subject,
        email_id=response.get("id"),
    )
    return True


async def send_automation_email(
    to_email: str,
    subject: str,
    body: str,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Send an automation-triggered email to a contact via Resend.

    ``body`` is rendered template text (placeholders already substituted by the
    automation worker). Returns True only when the provider accepted the send.
    """
    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": _text_to_html(body),
    }

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "automation_email_sent",
        to_email=to_email,
        email_id=response.get("id"),
    )
    return True


def _campaign_html(body: str, unsubscribe_url: str | None) -> str:
    """Render marketing-campaign email HTML with a compliant unsubscribe footer.

    ``body`` is operator-authored copy (placeholders already substituted) and is
    HTML-escaped so it can never inject markup. Bulk/marketing email must carry a
    visible one-click unsubscribe link (CAN-SPAM), so the footer is always
    rendered when an ``unsubscribe_url`` is provided.
    """
    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    safe_body = html_escape(body).replace("\n", "<br>")
    footer = ""
    if unsubscribe_url:
        safe_url = html_escape(unsubscribe_url, quote=True)
        footer = (
            '<hr style="border:none;border-top:1px solid #eee;margin:32px 0 12px;">'
            '<p style="font-size:12px;color:#999;text-align:center;">'
            f"If you no longer wish to receive these emails, "
            f'<a href="{safe_url}" style="color:#999;">unsubscribe here</a>.'
            "</p>"
        )
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <p>{safe_body}</p>
    {footer}
</body>
</html>"""


async def send_campaign_email(
    to_email: str,
    subject: str,
    body: str,
    *,
    unsubscribe_url: str | None = None,
    idempotency_key: uuid.UUID | None = None,
) -> str | None:
    """Send one marketing-campaign email to a contact via Resend.

    ``subject`` and ``body`` are rendered template output (placeholders already
    substituted by the email campaign worker). Returns the provider message id on
    success, or ``None`` when the send was not accepted — the caller uses the id
    presence to mark the campaign contact SENT vs FAILED.
    """
    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": _campaign_html(body, unsubscribe_url),
    }

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return None

    email_id = response.get("id")
    logger.info("campaign_email_sent", to_email=to_email, email_id=email_id)
    return str(email_id) if email_id else None


async def send_invitation_email(
    to_email: str,
    workspace_name: str,
    inviter_name: str,
    invitation_url: str,
    role: str,
    message: str | None = None,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Send a workspace invitation email."""
    subject = f"You've been invited to join {workspace_name}"

    personal_message = ""
    if message:
        personal_message = f"""
        <p style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <em>"{message}"</em>
        </p>
        """

    role_display = "an administrator" if role == "admin" else "a team member"

    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    button_style = (
        "background-color: #000; color: #fff; padding: 12px 30px; "
        "text-decoration: none; border-radius: 5px; display: inline-block; font-weight: 500;"
    )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1a1a1a; margin-bottom: 5px;">You're Invited!</h1>
    </div>
    <p>Hi there,</p>
    <p>
        <strong>{inviter_name}</strong> has invited you to join
        <strong>{workspace_name}</strong> as {role_display}.
    </p>
    {personal_message}
    <div style="text-align: center; margin: 30px 0;">
        <a href="{invitation_url}" style="{button_style}">
            Accept Invitation
        </a>
    </div>
    <p style="color: #666; font-size: 14px;">
        This invitation will expire in 7 days.
        If you didn't expect this invitation, you can safely ignore this email.
    </p>
    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
    <p style="color: #999; font-size: 12px; text-align: center;">
        Sent from Maxteriors
    </p>
</body>
</html>"""

    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "invitation_email_sent",
        to_email=to_email,
        workspace=workspace_name,
        email_id=response.get("id"),
    )
    return True


async def send_voicemail_notification(
    to_email: str,
    workspace_name: str,
    contact_phone: str,
    summary: str,
    transcript: str,
    intent: str,
    urgency: str,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Email an operator about a new transcribed inbound voicemail."""
    subject = f"New Voicemail ({urgency.upper()}) — {contact_phone}"

    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    label_style = "color: #666; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;"
    value_style = "font-size: 16px; font-weight: 600; color: #1a1a1a; margin: 2px 0 16px 0;"

    # The transcript is caller-supplied text; escape it so it cannot inject markup.
    safe_transcript = html_escape(transcript) if transcript else "(no transcript available)"
    safe_summary = html_escape(summary) if summary else "(no summary)"
    safe_intent = html_escape(intent)

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1a1a1a; margin-bottom: 5px;">New Voicemail</h1>
    </div>
    <p>A new voicemail was left for <strong>{html_escape(workspace_name)}</strong>.</p>
    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 24px 0;">
        <p style="{label_style}">From</p>
        <p style="{value_style}">{html_escape(contact_phone)}</p>
        <p style="{label_style}">Intent</p>
        <p style="{value_style}">{safe_intent}</p>
        <p style="{label_style}">Urgency</p>
        <p style="{value_style}">{html_escape(urgency)}</p>
        <p style="{label_style}">Summary</p>
        <p style="{value_style}">{safe_summary}</p>
        <p style="{label_style}">Transcript</p>
        <p style="font-size: 15px; color: #333; margin: 2px 0;">{safe_transcript}</p>
    </div>
    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
    <p style="color: #999; font-size: 12px; text-align: center;">
        Sent by your AI voicemail assistant
    </p>
</body>
</html>"""

    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "voicemail_notification_sent",
        to_email=to_email,
        urgency=urgency,
        intent=intent,
        email_id=response.get("id"),
    )
    return True


async def send_taken_message_notification(
    to_email: str,
    workspace_name: str,
    caller_name: str | None,
    callback_number: str | None,
    reason: str | None,
    urgency: str,
    preferred_callback_time: str | None,
    message_body: str | None,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Email an operator about a message the AI receptionist took from a caller."""
    who = caller_name or callback_number or "a caller"
    subject = f"New Message ({urgency.upper()}) — {who}"

    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    label_style = "color: #666; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;"
    value_style = "font-size: 16px; font-weight: 600; color: #1a1a1a; margin: 2px 0 16px 0;"

    # All fields are caller-supplied free text; escape so they cannot inject markup.
    safe_caller = html_escape(caller_name) if caller_name else "(not given)"
    safe_number = html_escape(callback_number) if callback_number else "(not given)"
    safe_reason = html_escape(reason) if reason else "(not given)"
    safe_when = html_escape(preferred_callback_time) if preferred_callback_time else "(not given)"
    safe_message = html_escape(message_body) if message_body else "(no message)"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1a1a1a; margin-bottom: 5px;">New Message</h1>
    </div>
    <p>Your AI receptionist took a message for <strong>{html_escape(workspace_name)}</strong>.</p>
    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 24px 0;">
        <p style="{label_style}">From</p>
        <p style="{value_style}">{safe_caller}</p>
        <p style="{label_style}">Callback Number</p>
        <p style="{value_style}">{safe_number}</p>
        <p style="{label_style}">Reason</p>
        <p style="{value_style}">{safe_reason}</p>
        <p style="{label_style}">Urgency</p>
        <p style="{value_style}">{html_escape(urgency)}</p>
        <p style="{label_style}">Preferred Callback Time</p>
        <p style="{value_style}">{safe_when}</p>
        <p style="{label_style}">Message</p>
        <p style="font-size: 15px; color: #333; margin: 2px 0;">{safe_message}</p>
    </div>
    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
    <p style="color: #999; font-size: 12px; text-align: center;">
        Sent by your AI receptionist
    </p>
</body>
</html>"""

    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "taken_message_notification_sent",
        to_email=to_email,
        urgency=urgency,
        email_id=response.get("id"),
    )
    return True


async def send_payment_received_notification(
    to_email: str,
    workspace_name: str,
    amount: float,
    currency: str,
    description: str | None,
    idempotency_key: uuid.UUID | None = None,
    client_name: str | None = None,
    client_email: str | None = None,
    client_phone: str | None = None,
    quote_number: str | None = None,
) -> bool:
    """Email an operator a payment receipt with minimal CRM client details.

    Payment credentials and provider identifiers stay out of email; the provider
    remains the source of truth for payment status.
    """
    amount_str = f"{amount:.2f} {currency.upper()}"
    subject = f"Payment Received — {amount_str}"

    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    label_style = "color: #666; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;"
    value_style = "font-size: 16px; font-weight: 600; color: #1a1a1a; margin: 2px 0 16px 0;"

    # Every value can originate in customer/operator input; escape before interpolation.
    details = [
        ("Amount", amount_str),
        ("For", description or "(no description)"),
        ("Client", client_name),
        ("Client email", client_email),
        ("Client phone", client_phone),
        ("Quote", quote_number),
    ]
    detail_html = "".join(
        f'<p style="{label_style}">{html_escape(label)}</p>'
        f'<p style="{value_style}">{html_escape(value)}</p>'
        for label, value in details
        if value
    )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1a1a1a; margin-bottom: 5px;">Payment Received</h1>
    </div>
    <p>A customer payment was confirmed for <strong>{html_escape(workspace_name)}</strong>.</p>
    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 24px 0;">
        {detail_html}
    </div>
    <p style="color: #666; font-size: 13px;">The payment provider remains the source of truth.</p>
    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
    <p style="color: #999; font-size: 12px; text-align: center;">
        Sent by your CRM
    </p>
</body>
</html>"""

    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "payment_received_notification_sent",
        to_email=to_email,
        amount=amount,
        currency=currency,
        email_id=response.get("id"),
    )
    return True


async def send_invoice_email(
    to_email: str,
    workspace_name: str,
    invoice_number: str,
    amount_str: str,
    due_date: str | None = None,
    pay_url: str | None = None,
    notes: str | None = None,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Email a customer their invoice with an optional Stripe "Pay now" button.

    ``amount_str`` is the pre-formatted balance due (e.g. ``"250.00 USD"``).
    ``pay_url`` is the hosted Stripe Checkout URL; the button is omitted when it
    is ``None`` (e.g. Stripe not configured). ``notes`` is operator-authored free
    text and is HTML-escaped. Returns True only when the provider accepted the send.
    """
    subject = f"Invoice {invoice_number} from {workspace_name}"

    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    label_style = "color: #666; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;"
    value_style = "font-size: 16px; font-weight: 600; color: #1a1a1a; margin: 2px 0 16px 0;"

    due_row = ""
    if due_date:
        due_row = (
            f'<p style="{label_style}">Due</p><p style="{value_style}">{html_escape(due_date)}</p>'
        )

    notes_block = ""
    if notes:
        notes_block = f'<p style="color: #555; margin: 24px 0;">{html_escape(notes)}</p>'

    pay_button = ""
    if pay_url:
        # pay_url is a Stripe-generated Checkout URL, not user input.
        pay_button = (
            '<div style="text-align: center; margin: 32px 0;">'
            f'<a href="{html_escape(pay_url)}" '
            'style="background-color: #1a1a1a; color: #ffffff; padding: 14px 28px; '
            "border-radius: 8px; text-decoration: none; font-weight: 600; "
            'display: inline-block;">Pay now</a></div>'
        )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1a1a1a; margin-bottom: 5px;">Invoice {html_escape(invoice_number)}</h1>
    </div>
    <p>You have a new invoice from <strong>{html_escape(workspace_name)}</strong>.</p>
    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 24px 0;">
        <p style="{label_style}">Amount due</p>
        <p style="{value_style}">{html_escape(amount_str)}</p>
        {due_row}
    </div>
    {pay_button}
    {notes_block}
    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
    <p style="color: #999; font-size: 12px; text-align: center;">
        Sent by {html_escape(workspace_name)} via Maxteriors
    </p>
</body>
</html>"""

    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "invoice_email_sent",
        to_email=to_email,
        invoice_number=invoice_number,
        email_id=response.get("id"),
    )
    return True


async def send_quote_email(
    to_email: str,
    workspace_name: str,
    quote_number: str,
    amount_str: str,
    title: str | None = None,
    expiry_date: str | None = None,
    notes: str | None = None,
    proposal_url: str | None = None,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Email a customer their quote/estimate.

    ``amount_str`` is the pre-formatted quoted total (e.g. ``"250.00 USD"``).
    ``title`` and ``notes`` are operator-authored free text and are HTML-escaped.
    ``proposal_url`` is the client-facing proposal page link; when provided a
    prominent "View your proposal" button is rendered so the customer can open,
    review, and approve/decline online. Returns True only when the provider
    accepted the send.
    """
    subject = f"Quote {quote_number} from {workspace_name}"

    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    label_style = "color: #666; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;"
    value_style = "font-size: 16px; font-weight: 600; color: #1a1a1a; margin: 2px 0 16px 0;"

    title_row = ""
    if title:
        title_row = (
            f'<p style="{label_style}">For</p><p style="{value_style}">{html_escape(title)}</p>'
        )

    expiry_row = ""
    if expiry_date:
        expiry_row = (
            f'<p style="{label_style}">Valid until</p>'
            f'<p style="{value_style}">{html_escape(expiry_date)}</p>'
        )

    notes_block = ""
    if notes:
        notes_block = f'<p style="color: #555; margin: 24px 0;">{html_escape(notes)}</p>'

    view_button = ""
    if proposal_url:
        # proposal_url is built server-side from settings.frontend_url + the
        # quote's own share token, not user input.
        view_button = (
            '<div style="text-align: center; margin: 32px 0;">'
            f'<a href="{html_escape(proposal_url)}" '
            'style="background-color: #1a1a1a; color: #ffffff; padding: 14px 28px; '
            "border-radius: 8px; text-decoration: none; font-weight: 600; "
            'display: inline-block;">View your proposal</a></div>'
        )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1a1a1a; margin-bottom: 5px;">Quote {html_escape(quote_number)}</h1>
    </div>
    <p>You have a new quote from <strong>{html_escape(workspace_name)}</strong>.</p>
    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 24px 0;">
        {title_row}
        <p style="{label_style}">Total</p>
        <p style="{value_style}">{html_escape(amount_str)}</p>
        {expiry_row}
    </div>
    {view_button}
    {notes_block}
    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
    <p style="color: #999; font-size: 12px; text-align: center;">
        Sent by {html_escape(workspace_name)} via Maxteriors
    </p>
</body>
</html>"""

    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "quote_email_sent",
        to_email=to_email,
        quote_number=quote_number,
        email_id=response.get("id"),
    )
    return True


async def send_estimate_email(
    to_email: str,
    workspace_name: str,
    estimate_url: str,
    client_name: str | None = None,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Email a customer their roofline lighting estimate.

    ``estimate_url`` is the client-facing permanent-vs-seasonal comparison page
    (built server-side from ``settings.frontend_url`` + the comparison's own share
    token, not user input). ``client_name`` is operator-authored free text and is
    HTML-escaped. Returns True only when the provider accepted the send.
    """
    subject = f"Your lighting estimate from {workspace_name}"

    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    button_style = (
        "background-color: #1a1a1a; color: #ffffff; padding: 14px 28px; "
        "border-radius: 8px; text-decoration: none; font-weight: 600; display: inline-block;"
    )

    greeting = f"Hi {html_escape(client_name)}," if client_name else "Hi there,"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1a1a1a; margin-bottom: 5px;">Your Lighting Estimate</h1>
    </div>
    <p>{greeting}</p>
    <p>
        Your personalized lighting estimate from
        <strong>{html_escape(workspace_name)}</strong> is ready. See how permanent
        lighting compares to seasonal installs — and what you'd save over time.
    </p>
    <div style="text-align: center; margin: 32px 0;">
        <a href="{html_escape(estimate_url)}" style="{button_style}">View your estimate</a>
    </div>
    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
    <p style="color: #999; font-size: 12px; text-align: center;">
        Sent by {html_escape(workspace_name)} via Maxteriors
    </p>
</body>
</html>"""

    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "estimate_email_sent",
        to_email=to_email,
        email_id=response.get("id"),
    )
    return True


async def send_appointment_booked_notification(
    to_email: str,
    owner_name: str,
    contact_name: str,
    contact_phone: str,
    appointment_time: datetime,
    calcom_booking_url: str | None = None,
    idempotency_key: uuid.UUID | None = None,
    timezone: str | None = None,
    ics_content: str | None = None,
) -> bool:
    """Notify the assigned rep (or workspace owner) that an appointment was booked.

    ``timezone`` is the workspace's IANA zone; the time is rendered there rather
    than in the UTC the row is stored in.

    ``ics_content`` is a rendered iCalendar document. Attaching it is what puts
    the appointment on the recipient's real calendar (Google/Apple/Outlook) —
    without it the notification is just an email they have to transcribe by hand.
    """
    subject = f"New Appointment Booked — {contact_name}"

    formatted_time = format_local_datetime(appointment_time, timezone)

    calcom_button = ""
    if calcom_booking_url:
        button_style = (
            "background-color: #000; color: #fff; padding: 12px 30px; "
            "text-decoration: none; border-radius: 5px; display: inline-block; font-weight: 500;"
        )
        calcom_button = f"""
    <div style="text-align: center; margin: 30px 0;">
        <a href="{calcom_booking_url}" style="{button_style}">
            View in Cal.com
        </a>
    </div>"""

    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    label_style = "color: #666; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;"
    value_style = "font-size: 16px; font-weight: 600; color: #1a1a1a; margin: 2px 0 16px 0;"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1a1a1a; margin-bottom: 5px;">New Appointment Booked!</h1>
    </div>
    <p>Hi {owner_name},</p>
    <p>
        Great news! Your AI agent just booked an appointment with one of your leads.
    </p>
    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 24px 0;">
        <p style="{label_style}">Lead Name</p>
        <p style="{value_style}">{contact_name}</p>
        <p style="{label_style}">Phone Number</p>
        <p style="{value_style}">{contact_phone}</p>
        <p style="{label_style}">Appointment Time</p>
        <p style="{value_style}">{formatted_time}</p>
    </div>
    {calcom_button}
    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
    <p style="color: #999; font-size: 12px; text-align: center;">
        Sent by your AI Lead Reactivation system
    </p>
</body>
</html>"""

    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    if ics_content:
        params["attachments"] = [
            {
                "filename": "invite.ics",
                "content": list(ics_content.encode("utf-8")),
                # ``method=REQUEST`` is what makes mail clients render the invite
                # with Accept/Decline instead of a generic file attachment.
                "content_type": "text/calendar; charset=utf-8; method=REQUEST",
            }
        ]

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "appointment_booked_notification_sent",
        to_email=to_email,
        contact_name=contact_name,
        email_id=response.get("id"),
    )
    return True


async def send_appointment_confirmation_to_attendee(
    to_email: str,
    contact_name: str,
    business_name: str,
    appointment_time: datetime,
    service_type: str | None = None,
    location: str | None = None,
    timezone: str | None = None,
    ics_content: str | None = None,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Email the customer their booking confirmation with a calendar invite.

    The customer previously got only an SMS, so the appointment lived nowhere
    they'd be reminded by — attaching the ``.ics`` puts it on the calendar they
    already watch. Transactional and appointment-scoped, so no unsubscribe
    footer, matching the other booking notifications.

    All interpolated values are contact/operator-derived free text and are
    HTML-escaped here so they cannot inject markup.
    """
    formatted_time = format_local_datetime(appointment_time, timezone)
    safe_business = html_escape(business_name or "our team")
    safe_name = html_escape(contact_name or "there")
    subject = f"Appointment confirmed — {formatted_time}"

    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    label_style = "color: #666; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;"
    value_style = "font-size: 16px; font-weight: 600; color: #1a1a1a; margin: 2px 0 16px 0;"

    detail_rows = (
        f'<p style="{label_style}">When</p>'
        f'<p style="{value_style}">{html_escape(formatted_time)}</p>'
    )
    if service_type:
        detail_rows += (
            f'<p style="{label_style}">Service</p>'
            f'<p style="{value_style}">{html_escape(service_type)}</p>'
        )
    if location:
        detail_rows += (
            f'<p style="{label_style}">Location</p>'
            f'<p style="{value_style}">{html_escape(location)}</p>'
        )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <h1 style="color: #1a1a1a; margin-bottom: 5px;">You're all set</h1>
    <p>Hi {safe_name},</p>
    <p>Your appointment with {safe_business} is confirmed. The calendar invite is
       attached, so you can add it to your calendar in one tap.</p>
    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 24px 0;">
        {detail_rows}
    </div>
    <p>Need to change or cancel? Just reply to the text message from
       {safe_business} and we'll take care of it.</p>
</body>
</html>"""

    params: dict[str, Any] = {
        "from": _from_address(),
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    if ics_content:
        params["attachments"] = [
            {
                "filename": "invite.ics",
                "content": list(ics_content.encode("utf-8")),
                "content_type": "text/calendar; charset=utf-8; method=REQUEST",
            }
        ]

    response = await _send(params, idempotency_key=idempotency_key)
    if response is None:
        return False

    logger.info(
        "appointment_attendee_confirmation_sent",
        to_email=to_email,
        email_id=response.get("id"),
    )
    return True


async def send_appointment_reminder_email(
    to_email: str,
    contact_name: str,
    business_name: str,
    body_text: str,
    appointment_time: datetime,
    timezone: str | None = None,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Email a customer a reminder for an upcoming appointment.

    ``body_text`` is the same rendered copy the SMS reminder uses, so the two
    channels can never quote different times for the same appointment.
    """
    formatted_time = format_local_datetime(appointment_time, timezone)
    subject = f"Reminder: your appointment {formatted_time}"

    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
    )
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="{body_style}">
    <p>{html_escape(body_text).replace(chr(10), "<br>")}</p>
    <p style="color: #666; font-size: 13px;">
        {html_escape(formatted_time)} &middot; {html_escape(business_name or "")}
    </p>
</body>
</html>"""

    response = await _send(
        {
            "from": _from_address(),
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        },
        idempotency_key=idempotency_key,
    )
    if response is None:
        return False

    logger.info(
        "appointment_reminder_email_sent",
        to_email=to_email,
        contact_name=contact_name,
        email_id=response.get("id"),
    )
    return True
