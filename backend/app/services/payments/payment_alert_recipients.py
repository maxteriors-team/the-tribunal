"""Resolve payment-alert email recipients independently of CRM access roles."""

import uuid
from dataclasses import dataclass

import structlog
from pydantic import BaseModel, EmailStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import Workspace
from app.services import notification_recipients

logger = structlog.get_logger()
SETTINGS_KEY = "payment_alerts"


class _PaymentAlertSettings(BaseModel):
    recipient_email: EmailStr


@dataclass(frozen=True, slots=True)
class PaymentAlertRecipient:
    email: str
    dedupe_identity: str | int


async def payment_alert_email_recipients(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    workspace: Workspace | None,
) -> list[PaymentAlertRecipient]:
    """Return one configured payment inbox, otherwise opted-in global operators."""
    workspace_settings = getattr(workspace, "settings", None)
    raw = workspace_settings.get(SETTINGS_KEY) if isinstance(workspace_settings, dict) else None
    if raw is not None:
        try:
            configured = _PaymentAlertSettings.model_validate(raw)
        except ValidationError:
            logger.error(
                "payment_alert_recipient_invalid",
                workspace_id=str(workspace_id),
            )
            return []
        email = str(configured.recipient_email).lower()
        return [PaymentAlertRecipient(email=email, dedupe_identity=f"configured:{email}")]

    users = await notification_recipients.workspace_notification_email_users(db, workspace_id)
    recipients: list[PaymentAlertRecipient] = []
    seen_emails: set[str] = set()
    for user in users:
        if not user.notification_email or not user.email:
            continue
        normalized_email = user.email.strip().lower()
        if normalized_email in seen_emails:
            continue
        seen_emails.add(normalized_email)
        recipients.append(
            PaymentAlertRecipient(
                email=user.email,
                dedupe_identity=user.id,
            )
        )
    return recipients
