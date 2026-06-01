"""Email service for sending transactional emails via Resend."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

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
    name = settings.resend_from_name or "AI CRM"
    email = settings.resend_from_email or "noreply@example.com"
    return f"{name} <{email}>"


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
        Sent from AI CRM
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


async def send_appointment_booked_notification(
    to_email: str,
    realtor_name: str,
    contact_name: str,
    contact_phone: str,
    appointment_time: datetime,
    calcom_booking_url: str | None = None,
    idempotency_key: uuid.UUID | None = None,
) -> bool:
    """Send an email notification to the realtor when an appointment is booked."""
    subject = f"New Appointment Booked — {contact_name}"

    formatted_time = appointment_time.strftime("%A, %B %-d at %-I:%M %p UTC")

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
    <p>Hi {realtor_name},</p>
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
