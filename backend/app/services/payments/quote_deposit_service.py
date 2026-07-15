"""Stripe-backed deposit collection for public client proposals.

When an operator sets a deposit percentage on a quote, the client can pay that
deposit online from the public proposal page to accept it. This module owns the
Stripe boundary for that flow: it turns a proposal token into a hosted Checkout
Session and reconciles the ``checkout.session.completed`` webhook back onto the
quote (idempotently). It reuses the generic one-off payment helpers in
:mod:`app.services.payments.call_payment_service`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from app.services.payments import call_payment_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.quote import Quote

logger = structlog.get_logger()

# Stripe metadata key that tags a Checkout Session as a proposal deposit so the
# shared billing webhook routes it here (and not to subscriptions / in-call).
DEPOSIT_KIND = "quote_deposit"


class DepositError(Exception):
    """A deposit checkout could not be started (bad state or Stripe missing)."""


@dataclass(slots=True)
class DepositCheckout:
    """Resolved hosted Checkout Session for a proposal deposit."""

    url: str
    amount: float
    currency: str


def resolve_deposit(mode: str, value: float, total: float) -> float:
    """Resolve a deposit amount (major units) for a mode/value against a total.

    ``fixed`` clamps to the total; ``percentage`` takes ``value``% of it. Returns
    0 for a non-positive value or total. Pure — shared by the wizard preview and
    the persisted-quote resolver so display and charge math never diverge.
    """
    if value <= 0 or total <= 0:
        return 0.0
    if mode == "fixed":
        return round(min(value, total), 2)
    return round(total * value / 100, 2)


def deposit_amount(quote: Quote) -> float | None:
    """Return the derived deposit amount (major units), or None when not set.

    A fixed amount (``deposit_amount_fixed``) takes precedence over a percentage
    and is clamped to the quote total so a deposit never exceeds what's owed.
    Returns None when no deposit is requested or the amount resolves to zero.
    """
    total = float(quote.total or 0)
    fixed = getattr(quote, "deposit_amount_fixed", None)
    if fixed is not None:
        amount = float(fixed)
        if amount <= 0:
            return None
        return round(min(amount, total), 2) if total > 0 else round(amount, 2)
    if quote.deposit_percentage is None:
        return None
    pct = float(quote.deposit_percentage)
    if pct <= 0:
        return None
    return round(total * pct / 100, 2)


async def create_deposit_checkout_session(
    db: AsyncSession,
    token: str,
) -> DepositCheckout:
    """Start a Stripe Checkout Session for a proposal's deposit.

    Raises :class:`DepositError` (mapped to a 4xx/503 by the route) when Stripe
    is not configured, the quote requests no deposit, the deposit is already
    paid, or the proposal is expired/declined and can no longer be accepted.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.quote import Quote
    from app.services.quotes.proposal_template import get_proposal_template

    if not call_payment_service.is_payment_configured():
        raise DepositError("Online payment is not configured for this business.")

    result = await db.execute(
        select(Quote)
        .where(Quote.public_token == token)
        .options(selectinload(Quote.contact), selectinload(Quote.workspace))
    )
    quote = result.scalar_one_or_none()
    if quote is None or quote.status == "draft":
        raise DepositError("Proposal not found.")
    if quote.status in {"declined", "expired"}:
        raise DepositError("This proposal can no longer be paid.")
    if quote.deposit_paid_at is not None:
        raise DepositError("This deposit has already been paid.")

    amount = deposit_amount(quote)
    if amount is None or amount <= 0:
        raise DepositError("No deposit is due on this proposal.")

    template = get_proposal_template(quote.workspace)
    business_name = template.business_name or (
        quote.workspace.name if quote.workspace else "Deposit"
    )
    customer_email = quote.contact.email if quote.contact else None
    metadata = {
        "kind": DEPOSIT_KIND,
        "quote_id": str(quote.id),
        "workspace_id": str(quote.workspace_id),
    }
    # Return the client to their proposal so they immediately see "deposit paid".
    from app.core.config import settings

    proposal_url = f"{settings.frontend_url}/p/quotes/{token}"

    session = await call_payment_service.create_payment_checkout_session(
        amount=amount,
        currency=quote.currency,
        product_name=f"{business_name} — Deposit for {quote.number}",
        metadata=metadata,
        customer_email=customer_email,
        success_url=f"{proposal_url}?deposit=paid",
        cancel_url=proposal_url,
    )
    if session.url is None:
        raise DepositError("Could not start the payment. Please try again.")

    quote.deposit_checkout_session_id = session.session_id
    if session.payment_intent_id:
        quote.deposit_payment_intent_id = session.payment_intent_id
    await db.commit()

    logger.info(
        "quote_deposit_checkout_created",
        quote_id=str(quote.id),
        workspace_id=str(quote.workspace_id),
        amount=amount,
        currency=quote.currency,
    )
    return DepositCheckout(url=session.url, amount=amount, currency=quote.currency)


@dataclass(slots=True)
class DepositStatus:
    """Reconciled deposit state returned to the public page."""

    deposit_paid: bool
    deposit_amount: float | None
    currency: str


async def reconcile_deposit(db: AsyncSession, token: str) -> DepositStatus:
    """Reconcile a proposal's deposit against Stripe on return from checkout.

    Backstop for the webhook: when the client lands back on the proposal we ask
    Stripe for the stored Checkout Session's status and mark the deposit paid if
    Stripe says it's paid. Idempotent and safe to call repeatedly; a no-op when
    there's no deposit, no session, or Stripe is unconfigured. Never raises for
    a normal "not paid yet" — it just reports the current state.
    """
    from sqlalchemy import select

    from app.models.quote import Quote

    result = await db.execute(select(Quote).where(Quote.public_token == token))
    quote = result.scalar_one_or_none()
    if quote is None or quote.status == "draft":
        raise DepositError("Proposal not found.")

    amount = deposit_amount(quote)
    if quote.deposit_paid_at is not None:
        return DepositStatus(deposit_paid=True, deposit_amount=amount, currency=quote.currency)

    session_id = quote.deposit_checkout_session_id
    if session_id and call_payment_service.is_payment_configured():
        try:
            status = await call_payment_service.retrieve_session_status(session_id)
        except Exception as exc:  # pragma: no cover - Stripe/network best-effort
            logger.warning(
                "quote_deposit_reconcile_failed",
                quote_id=str(quote.id),
                error=str(exc),
            )
        else:
            if status.payment_status == "paid":
                await mark_deposit_paid(db, quote, payment_intent_id=status.payment_intent_id)
                return DepositStatus(
                    deposit_paid=True, deposit_amount=amount, currency=quote.currency
                )

    return DepositStatus(deposit_paid=False, deposit_amount=amount, currency=quote.currency)


async def mark_deposit_paid(
    db: AsyncSession,
    quote: Quote,
    *,
    payment_intent_id: str | None = None,
) -> bool:
    """Mark a quote's deposit paid (idempotent). Returns True on the transition."""
    if quote.deposit_paid_at is not None:
        return False
    quote.deposit_paid_at = datetime.now(UTC)
    if payment_intent_id:
        quote.deposit_payment_intent_id = payment_intent_id
    await db.commit()
    logger.info(
        "quote_deposit_marked_paid",
        quote_id=str(quote.id),
        workspace_id=str(quote.workspace_id),
    )
    return True


async def handle_deposit_checkout_session_completed(
    session: dict[str, Any],
    db: AsyncSession,
) -> None:
    """Reconcile a Stripe ``checkout.session.completed`` event for a deposit.

    Resolves the quote from session metadata (or the stored session id) and
    marks its deposit paid exactly once.
    """
    from sqlalchemy import select

    from app.models.quote import Quote

    metadata = session.get("metadata") or {}
    quote_id = metadata.get("quote_id")
    session_id = session.get("id")

    quote: Quote | None = None
    if quote_id:
        try:
            quote = await db.get(Quote, uuid.UUID(quote_id))
        except ValueError:
            quote = None
    if quote is None and session_id:
        result = await db.execute(
            select(Quote).where(Quote.deposit_checkout_session_id == session_id)
        )
        quote = result.scalar_one_or_none()

    if quote is None:
        logger.warning(
            "quote_deposit_webhook_no_match",
            quote_id=quote_id,
            session_id=session_id,
        )
        return

    payment_intent = session.get("payment_intent")
    payment_intent_id = payment_intent if isinstance(payment_intent, str) else None
    await mark_deposit_paid(db, quote, payment_intent_id=payment_intent_id)
