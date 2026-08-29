"""Tell the company when a customer pays online (push + email).

In-call payments have notified operators since they shipped
(``call_payment_service.notify_payment_operators``), but the two *self-serve*
money paths -- a deposit paid on a public proposal and a balance paid on a public
invoice -- notified nobody. Money arrived, the record updated, and the only way
to find out was to open the dashboard and look.

That is the same class of silent failure as the invoice email that reported
success while reaching no one: the system is fine, and the human is uninformed.

Both callers route through here so a deposit and an invoice payment produce the
same push, the same email, and the same idempotency behaviour. Every send is
best-effort: a payment is already banked by the time we get here, so a mail or
push outage must never roll it back or raise.
"""

import uuid
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


async def notify_customer_payment(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    amount: float | Decimal,
    currency: str,
    description: str,
    idempotency_scope: str,
    idempotency_id: uuid.UUID,
    deep_link: str | None = None,
    client_name: str | None = None,
    client_email: str | None = None,
    client_phone: str | None = None,
    quote_number: str | None = None,
) -> int:
    """Push every member and email the configured payment-alert recipient.

    ``idempotency_scope``/``idempotency_id`` are folded into the per-recipient
    outbound key, so a Stripe webhook retry that re-confirms the same payment
    cannot send a second email. Callers are additionally expected to be
    idempotent themselves (``record_payment`` dedupes on the payment-intent id;
    ``mark_deposit_paid`` returns early once ``deposit_paid_at`` is set), so this
    is a second line of defence rather than the only one.

    Returns the number of emails accepted, for logging. Never raises.
    """
    from app.models.workspace import Workspace
    from app.services.email import send_payment_received_notification
    from app.services.idempotency import derive_outbound_key
    from app.services.payments.payment_alert_recipients import (
        payment_alert_email_recipients,
    )
    from app.services.push_notifications import push_notification_service

    workspace = await db.get(Workspace, workspace_id)
    workspace_name = workspace.name if workspace else "your workspace"
    amount_value = float(amount)
    amount_str = f"{amount_value:.2f} {currency.upper()}"

    try:
        await push_notification_service.send_to_workspace_members(
            db=db,
            workspace_id=str(workspace_id),
            title="Payment Received",
            body=f"{amount_str} — {description}"[:300],
            data={
                "type": "payment",
                "screen": deep_link or "/(tabs)",
            },
            notification_type="payment",
            # Reuses the existing generic alert channel rather than inventing a
            # "payments" one: Android channels are declared by the mobile app, and
            # an unknown channelId can silently suppress the notification.
            channel_id="alerts",
        )
    except Exception as exc:  # pragma: no cover - best-effort push
        logger.warning(
            "customer_payment_push_failed",
            workspace_id=str(workspace_id),
            error=str(exc),
        )

    sent = 0
    try:
        recipients = await payment_alert_email_recipients(
            db, workspace_id=workspace_id, workspace=workspace
        )
        for recipient in recipients:
            ok = await send_payment_received_notification(
                to_email=recipient.email,
                workspace_name=workspace_name,
                amount=amount_value,
                currency=currency,
                description=description,
                client_name=client_name,
                client_email=client_email,
                client_phone=client_phone,
                quote_number=quote_number,
                idempotency_key=derive_outbound_key(
                    idempotency_scope, idempotency_id, recipient.dedupe_identity
                ),
            )
            sent += 1 if ok else 0
    except Exception as exc:  # pragma: no cover - best-effort email
        logger.warning(
            "customer_payment_email_failed",
            workspace_id=str(workspace_id),
            error=str(exc),
        )

    logger.info(
        "customer_payment_notified",
        workspace_id=str(workspace_id),
        amount=amount_value,
        scope=idempotency_scope,
        emails_sent=sent,
    )
    return sent
