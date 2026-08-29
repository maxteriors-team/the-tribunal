"""Deposit collection and offline recording for client proposals.

When an operator sets deposit terms, the client can pay by card from the public
proposal or an authenticated operator can attest that cash, a check, or another
offline method was received. This module owns both paths so the first paid
transition is atomic, carries durable provenance, and closes any open Stripe
Checkout Session before an offline payment can be recorded.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from app.models.contact import Contact
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.services.payments import call_payment_service
from app.services.quotes.ownership import quote_owner_predicate

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


def deposit_for_total(quote: Quote, total: float) -> float | None:
    """Deposit owed on ``total`` under this quote's deposit terms, or None.

    Split out from :func:`deposit_amount` so the client proposal page can price
    "due today" for *each* package it offers without re-implementing the rule:
    a fixed amount (``deposit_amount_fixed``) takes precedence over a percentage
    and is clamped so a deposit never exceeds what's owed. Returns None when no
    deposit is requested or the amount resolves to zero.
    """
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


def deposit_amount(quote: Quote) -> float | None:
    """Return the derived deposit amount (major units), or None when not set."""
    return deposit_for_total(quote, float(quote.total or 0))


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


async def _retrieve_checkout_status_for_manual(
    quote: Quote,
    session_id: str,
) -> call_payment_service.SessionStatus:
    """Read Stripe state without leaking provider errors through the API."""
    try:
        return await call_payment_service.retrieve_session_status(session_id)
    except Exception as exc:
        logger.warning(
            "quote_manual_deposit_checkout_lookup_failed",
            quote_id=str(quote.id),
            session_id=session_id,
            error=str(exc),
        )
        raise ServiceUnavailableError(
            "The online payment link could not be checked. Try again before recording this deposit."
        ) from exc


async def _prepare_checkout_for_manual_deposit(
    db: AsyncSession,
    quote: Quote,
) -> bool:
    """Close an open checkout; return True if Stripe had already been paid."""
    session_id = quote.deposit_checkout_session_id
    if not session_id:
        return False
    if not call_payment_service.is_payment_configured():
        raise ServiceUnavailableError(
            "The online payment link could not be closed safely. Try again when "
            "card payments are available."
        )

    checkout_status = await _retrieve_checkout_status_for_manual(quote, session_id)
    # A paid card session wins over an operator's later manual attestation.
    if checkout_status.payment_status == "paid":
        await mark_deposit_paid(
            db,
            quote,
            payment_intent_id=checkout_status.payment_intent_id,
        )
        return True
    if checkout_status.status != "open":
        return False

    try:
        expired = await call_payment_service.expire_checkout_session_if_open(session_id)
    except Exception as exc:
        logger.warning(
            "quote_manual_deposit_checkout_expire_failed",
            quote_id=str(quote.id),
            session_id=session_id,
            error=str(exc),
        )
        raise ServiceUnavailableError(
            "The online payment link could not be closed. Try again before recording this deposit."
        ) from exc
    if expired:
        return False

    # The session changed between lookup and expiry. Reconcile once more rather
    # than risk recording two payments.
    checkout_status = await _retrieve_checkout_status_for_manual(quote, session_id)
    if checkout_status.payment_status == "paid":
        await mark_deposit_paid(
            db,
            quote,
            payment_intent_id=checkout_status.payment_intent_id,
        )
        return True
    raise ConflictError(
        "The online payment changed state. Refresh the quote and try again.",
        code="deposit_checkout_state_changed",
    )


async def record_manual_deposit(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    *,
    payment_method: str,
    recorded_by_id: int,
    owner_user_id: int | None = None,
) -> Quote:
    """Record an offline deposit received by an authenticated operator.

    An existing Checkout Session is reconciled and, while still open, expired
    before the transition. Failing closed here prevents a customer with an older
    browser tab from paying by card after the operator records cash or a check.
    """
    from sqlalchemy import select

    from app.models.quote import Quote

    if payment_method not in {"cash", "check", "other"}:
        raise ValidationError(
            "Manual deposits must use cash, check, or other.",
            code="invalid_deposit_payment_method",
        )

    result = await db.execute(
        select(Quote)
        .where(
            Quote.id == quote_id,
            Quote.workspace_id == workspace_id,
            quote_owner_predicate(owner_user_id),
        )
        .with_for_update()
    )
    quote = result.scalar_one_or_none()
    if quote is None:
        raise NotFoundError("Quote not found", code="quote_not_found")
    if quote.deposit_paid_at is not None:
        raise ConflictError(
            "This deposit has already been completed.",
            code="deposit_already_paid",
        )
    if quote.status in {"declined", "expired"}:
        raise ConflictError(
            "A deposit cannot be recorded on a declined or expired quote.",
            code="deposit_quote_inactive",
        )

    amount = deposit_amount(quote)
    if amount is None or amount <= 0:
        raise ValidationError(
            "No deposit is due on this quote.",
            code="deposit_not_required",
        )

    if await _prepare_checkout_for_manual_deposit(db, quote):
        return quote

    transitioned = await mark_deposit_paid(
        db,
        quote,
        payment_method=payment_method,
        recorded_by_id=recorded_by_id,
        notify=False,
    )
    if not transitioned:
        raise ConflictError(
            "This deposit has already been completed.",
            code="deposit_already_paid",
        )
    return quote


async def mark_deposit_paid(
    db: AsyncSession,
    quote: Quote,
    *,
    payment_intent_id: str | None = None,
    payment_method: str = "card",
    recorded_by_id: int | None = None,
    notify: bool = True,
) -> bool:
    """Atomically mark a deposit paid; return ``True`` only for the winner."""
    from sqlalchemy import update

    from app.models.quote import Quote

    if quote.deposit_paid_at is not None:
        return False

    paid_at = datetime.now(UTC)
    values: dict[str, Any] = {
        "deposit_paid_at": paid_at,
        "deposit_payment_method": payment_method,
        "deposit_recorded_by_id": recorded_by_id,
    }
    if payment_intent_id:
        values["deposit_payment_intent_id"] = payment_intent_id

    result = await db.execute(
        update(Quote)
        .where(Quote.id == quote.id, Quote.deposit_paid_at.is_(None))
        .values(**values)
        .returning(Quote.id)
        .execution_options(synchronize_session=False)
    )
    transitioned = result.scalar_one_or_none() is not None
    await db.commit()
    if not transitioned:
        await db.refresh(quote)
        return False

    await db.refresh(quote)
    logger.info(
        "quote_deposit_marked_paid",
        quote_id=str(quote.id),
        workspace_id=str(quote.workspace_id),
        payment_method=payment_method,
        recorded_by_id=recorded_by_id,
    )
    await _confirm_prebooking(db, quote)
    if notify:
        await _notify_deposit_paid(db, quote)
    return True


async def _notify_deposit_paid(db: AsyncSession, quote: Quote) -> None:
    """Tell the company a customer just paid their deposit.

    Hung off the single paid transition (guarded by ``deposit_paid_at``), so the
    Stripe webhook and the return-from-checkout backstop both land here exactly
    once. Best-effort: the money is already taken, so a notification failure must
    never turn a successful payment into a webhook Stripe retries forever.
    """
    from app.services.payments.customer_payment_notifications import (
        notify_customer_payment,
    )

    amount = deposit_amount(quote) or 0.0
    if amount <= 0:
        return
    contact = await db.get(Contact, quote.contact_id) if quote.contact_id is not None else None
    client_name = None
    if contact is not None:
        client_name = (
            " ".join(part for part in (contact.first_name, contact.last_name) if part) or None
        )
    try:
        await notify_customer_payment(
            db,
            workspace_id=quote.workspace_id,
            amount=amount,
            currency=quote.currency,
            description=f"Deposit on {quote.number}",
            idempotency_scope="quote_deposit_operator_email",
            idempotency_id=quote.id,
            deep_link="/(tabs)/quotes",
            client_name=client_name,
            client_email=contact.email if contact else None,
            client_phone=contact.phone_number if contact else None,
            quote_number=quote.number,
        )
    except Exception as exc:  # pragma: no cover - best-effort notification
        logger.warning("quote_deposit_notify_failed", quote_id=str(quote.id), error=str(exc))


async def _confirm_prebooking(db: AsyncSession, quote: Quote) -> None:
    """Turn a completed pre-booking deposit into a confirmed slot and queued job.

    Hung off the single paid transition so card and authenticated offline-payment
    paths both land here exactly once, and a pre-booking campaign needs no payment
    path of its own. A no-op for ordinary quotes.

    Failures are logged, never raised: payment is already complete and the deposit
    is already recorded, so a booking hiccup must not turn successful processing
    into retries. The confirmation is idempotent, so a later reconcile can fix it.
    """
    from app.services.prebooking.reservation_service import PreBookingReservationService

    # Read before the try: a rollback in the handler expires the instance, and
    # reading an expired attribute afterwards emits sync IO under asyncio.
    quote_id = str(quote.id)
    workspace_id = str(quote.workspace_id)
    try:
        await PreBookingReservationService(db).confirm_reservation_for_quote(quote)
    except Exception:
        logger.warning(
            "prebooking_confirmation_failed",
            quote_id=quote_id,
            workspace_id=workspace_id,
            exc_info=True,
        )
        # Leave the session usable for whatever the webhook handler does next.
        with suppress(Exception):
            await db.rollback()


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
