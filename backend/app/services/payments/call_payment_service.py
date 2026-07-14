"""Stripe-backed helpers for in-call payment / deposit collection.

The ``collect_payment`` voice tool never reads raw card numbers over the AI
channel. Instead it asks Stripe for a hosted Checkout Session for the requested
amount and texts the secure payment link to the caller. This module owns the
Stripe boundary plus status reconciliation and operator notification, keeping
the tool executor thin and testable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import stripe
import structlog

from app.core.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.call_payment import CallPayment

logger = structlog.get_logger()

# Guardrails on what the AI may charge in a single in-call request. Amounts are
# in major units (e.g. dollars). These cap blast radius if the model is coaxed
# into an absurd amount; operators can still take larger payments out of band.
MIN_PAYMENT_AMOUNT = 1.0
MAX_PAYMENT_AMOUNT = 10_000.0

# Stripe metadata key that tags a Checkout Session as an in-call payment so the
# shared billing webhook can route it away from the SaaS-subscription path.
PAYMENT_KIND = "in_call_payment"

_ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "bif",
        "clp",
        "djf",
        "gnf",
        "jpy",
        "kmf",
        "krw",
        "mga",
        "pyg",
        "rwf",
        "ugx",
        "vnd",
        "vuv",
        "xaf",
        "xof",
        "xpf",
    }
)


@dataclass(slots=True)
class CheckoutSessionResult:
    """Resolved Stripe Checkout Session for an in-call payment."""

    session_id: str
    url: str | None
    payment_intent_id: str | None


@dataclass(slots=True)
class SessionStatus:
    """Reconciled status of a Stripe Checkout Session."""

    payment_status: str  # "paid" | "unpaid" | "no_payment_required"
    status: str  # "open" | "complete" | "expired"
    payment_intent_id: str | None


def is_payment_configured() -> bool:
    """Return whether Stripe is configured for collecting payments."""
    return bool(settings.stripe_secret_key)


def to_minor_units(amount: float, currency: str) -> int:
    """Convert a major-unit amount (e.g. dollars) to Stripe's minor units."""
    if currency.lower() in _ZERO_DECIMAL_CURRENCIES:
        return int(round(amount))
    return int(round(amount * 100))


def from_minor_units(amount: int, currency: str) -> float:
    """Convert a Stripe minor-unit amount back to major units (e.g. dollars)."""
    if currency.lower() in _ZERO_DECIMAL_CURRENCIES:
        return float(amount)
    return round(amount / 100, 2)


def _stripe_client() -> stripe.StripeClient:
    return stripe.StripeClient(settings.stripe_secret_key)


async def create_payment_checkout_session(
    *,
    amount: float,
    currency: str,
    product_name: str,
    metadata: dict[str, str],
    customer_email: str | None = None,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> CheckoutSessionResult:
    """Create a Stripe Checkout Session (``payment`` mode) for a one-off payment.

    Reused for in-call payments and public-proposal deposits. ``success_url`` /
    ``cancel_url`` default to the generic payment result pages when omitted so
    callers that want to return the customer somewhere specific (e.g. back to a
    proposal) can override them.

    Raises ``stripe.StripeError`` on Stripe failures so the caller can surface a
    friendly message without persisting a dangling row.
    """
    client = _stripe_client()
    params: dict[str, Any] = {
        "mode": "payment",
        "line_items": [
            {
                "price_data": {
                    "currency": currency,
                    "product_data": {"name": product_name},
                    "unit_amount": to_minor_units(amount, currency),
                },
                "quantity": 1,
            }
        ],
        "success_url": success_url or f"{settings.frontend_url}/payment-complete",
        "cancel_url": cancel_url or f"{settings.frontend_url}/payment-cancelled",
        "metadata": metadata,
        "payment_intent_data": {"metadata": metadata},
    }
    if customer_email:
        params["customer_email"] = customer_email

    session = client.checkout.sessions.create(params=params)  # type: ignore[arg-type]
    payment_intent = getattr(session, "payment_intent", None)
    payment_intent_id = payment_intent if isinstance(payment_intent, str) else None
    return CheckoutSessionResult(
        session_id=session.id,
        url=session.url,
        payment_intent_id=payment_intent_id,
    )


async def retrieve_session_status(session_id: str) -> SessionStatus:
    """Fetch the current status of a Checkout Session from Stripe."""
    client = _stripe_client()
    session = client.checkout.sessions.retrieve(session_id)
    payment_intent = getattr(session, "payment_intent", None)
    payment_intent_id = payment_intent if isinstance(payment_intent, str) else None
    return SessionStatus(
        payment_status=str(getattr(session, "payment_status", "unpaid")),
        status=str(getattr(session, "status", "open")),
        payment_intent_id=payment_intent_id,
    )


async def mark_call_payment_paid(
    db: AsyncSession,
    payment: CallPayment,
    *,
    payment_intent_id: str | None = None,
    notify: bool = True,
) -> bool:
    """Mark a :class:`CallPayment` paid (idempotent) and notify operators once.

    Returns ``True`` when this call performed the paid transition, ``False`` if
    the payment was already recorded as paid (so callers can avoid duplicate
    side effects).
    """
    from app.models.call_payment import CallPaymentStatus

    if payment.status == CallPaymentStatus.PAID:
        return False

    payment.status = CallPaymentStatus.PAID
    payment.paid_at = datetime.now(UTC)
    if payment_intent_id:
        payment.stripe_payment_intent_id = payment_intent_id
    await db.commit()

    if notify:
        await notify_payment_operators(db, payment)

    logger.info(
        "call_payment_marked_paid",
        call_payment_id=str(payment.id),
        workspace_id=str(payment.workspace_id),
        amount=float(payment.amount),
        currency=payment.currency,
    )
    return True


async def handle_checkout_session_completed(
    session: dict[str, Any],
    db: AsyncSession,
) -> None:
    """Handle a Stripe ``checkout.session.completed`` event for an in-call payment.

    Resolves the :class:`CallPayment` from session metadata (or the session id)
    and marks it paid, notifying operators exactly once.
    """
    from sqlalchemy import select

    from app.models.call_payment import CallPayment

    metadata = session.get("metadata") or {}
    call_payment_id = metadata.get("call_payment_id")
    session_id = session.get("id")

    payment: CallPayment | None = None
    if call_payment_id:
        try:
            payment = await db.get(CallPayment, uuid.UUID(call_payment_id))
        except ValueError:
            payment = None
    if payment is None and session_id:
        result = await db.execute(
            select(CallPayment).where(CallPayment.stripe_checkout_session_id == session_id)
        )
        payment = result.scalar_one_or_none()

    if payment is None:
        logger.warning(
            "call_payment_webhook_no_match",
            call_payment_id=call_payment_id,
            session_id=session_id,
        )
        return

    payment_intent = session.get("payment_intent")
    payment_intent_id = payment_intent if isinstance(payment_intent, str) else None
    await mark_call_payment_paid(db, payment, payment_intent_id=payment_intent_id)


async def notify_payment_operators(db: AsyncSession, payment: CallPayment) -> None:
    """Notify workspace operators of a successful in-call payment (push + email).

    Guarded by ``operators_notified_at`` so the webhook and an in-call status
    poll racing to confirm the same payment never double-notify.
    """
    from sqlalchemy import select

    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMembership
    from app.services.email import send_payment_received_notification
    from app.services.idempotency import derive_outbound_key
    from app.services.push_notifications import push_notification_service

    if payment.operators_notified_at is not None:
        return

    payment.operators_notified_at = datetime.now(UTC)
    await db.commit()

    workspace = await db.get(Workspace, payment.workspace_id)
    workspace_name = workspace.name if workspace else "your workspace"
    amount_str = f"{float(payment.amount):.2f} {payment.currency.upper()}"

    try:
        await push_notification_service.send_to_workspace_members(
            db=db,
            workspace_id=str(payment.workspace_id),
            title="Payment Received",
            body=f"{amount_str} collected on a call"[:300],
            data={
                "type": "payment",
                "callPaymentId": str(payment.id),
                "screen": (
                    f"/(tabs)/calls/{payment.message_id}" if payment.message_id else "/(tabs)/calls"
                ),
            },
            notification_type="payment",
            channel_id="calls",
        )
    except Exception as exc:  # pragma: no cover - best-effort push
        logger.exception("call_payment_push_failed", error=str(exc))

    try:
        members = await db.execute(
            select(User)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .where(WorkspaceMembership.workspace_id == payment.workspace_id)
        )
        sent = 0
        for user in members.scalars().all():
            if not user.notification_email or not user.email:
                continue
            idem = derive_outbound_key("call_payment_email", payment.id, user.id)
            ok = await send_payment_received_notification(
                to_email=user.email,
                workspace_name=workspace_name,
                amount=float(payment.amount),
                currency=payment.currency,
                description=payment.description,
                idempotency_key=idem,
            )
            sent += 1 if ok else 0
        logger.info("call_payment_email_dispatched", recipients=sent)
    except Exception as exc:  # pragma: no cover - best-effort email
        logger.exception("call_payment_email_failed", error=str(exc))
