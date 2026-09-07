"""Hosted card payments for approved Permanent Lighting proposals.

This path intentionally does not reuse quote deposit fields. The accepted choice
and amount are immutable proposal evidence, while Stripe's signed session is
verified against that evidence before a payment can be recorded.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Literal, cast

import structlog

from app.services.idempotency import derive_outbound_key
from app.services.payments import call_payment_service
from app.services.payments.proposal_payment_access import proposal_payments_enabled

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.quote import Quote

logger = structlog.get_logger()

PROPOSAL_PAYMENT_KIND = "permanent_proposal_payment"
PaymentChoice = Literal["fifty_percent_down", "pay_in_full"]
_PAYMENT_CHOICES = {"fifty_percent_down", "pay_in_full"}


class ProposalPaymentError(Exception):
    """A Permanent proposal payment cannot safely proceed."""


class _SessionVerificationError(Exception):
    """Stripe session evidence does not match the accepted proposal."""


@dataclass(slots=True)
class ProposalPaymentCheckout:
    """Hosted Checkout Session returned to the public proposal."""

    url: str
    amount: float
    currency: str
    payment_choice: PaymentChoice


@dataclass(slots=True)
class ProposalPaymentStatus:
    """Reconciled Permanent proposal payment state."""

    payment_paid: bool
    payment_required: bool
    payment_amount: float
    completion_balance: float
    currency: str
    payment_choice: PaymentChoice


def _money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_permanent(quote: Quote) -> bool:
    document = quote.proposal_document
    service = document.get("service") if isinstance(document, Mapping) else None
    return isinstance(service, str) and service.strip().lower() == "permanent"


def _payment_state(quote: Quote) -> tuple[PaymentChoice, Decimal, Decimal]:
    """Return validated persisted payment truth and accepted full total."""
    if quote.status != "approved" or not _is_permanent(quote):
        raise ProposalPaymentError("This proposal is not approved for online payment.")
    choice = quote.proposal_payment_choice
    amount = quote.proposal_payment_amount
    if choice not in _PAYMENT_CHOICES or amount is None:
        raise ProposalPaymentError("This proposal has no accepted payment choice.")
    full = _money(quote.total or 0)
    persisted = _money(amount)
    expected = _money(full / 2) if choice == "fifty_percent_down" else full
    if full <= 0 or persisted != expected:
        raise ProposalPaymentError("This proposal's payment amount could not be verified.")
    if not quote.currency:
        raise ProposalPaymentError("This proposal's payment currency could not be verified.")
    return cast(PaymentChoice, choice), persisted, full


def _metadata(quote: Quote, choice: PaymentChoice) -> dict[str, str]:
    return {
        "kind": PROPOSAL_PAYMENT_KIND,
        "quote_id": str(quote.id),
        "workspace_id": str(quote.workspace_id),
        "proposal_payment_choice": choice,
    }


def _validate_session_identity(
    quote: Quote,
    session_id: str,
    details: call_payment_service.CheckoutSessionDetails,
    *,
    choice: PaymentChoice,
    amount: Decimal,
) -> None:
    """Require every provider field to match local immutable payment evidence."""
    if quote.proposal_payment_checkout_session_id != session_id:
        raise _SessionVerificationError("Checkout Session does not match this proposal.")
    if details.mode != "payment":
        raise _SessionVerificationError("Checkout Session mode does not match.")
    expected_metadata = _metadata(quote, choice)
    if any(details.metadata.get(key) != value for key, value in expected_metadata.items()):
        raise _SessionVerificationError("Checkout Session metadata does not match.")
    expected_minor = call_payment_service.to_minor_units(amount, quote.currency)
    if details.amount_total != expected_minor:
        raise _SessionVerificationError("Checkout Session amount does not match.")
    if details.currency != quote.currency.lower():
        raise _SessionVerificationError("Checkout Session currency does not match.")


def _paid_intent(quote: Quote, details: call_payment_service.CheckoutSessionDetails) -> str | None:
    """Return the PaymentIntent only for provider-confirmed completed payment."""
    if details.payment_status != "paid":
        return None
    if details.status != "complete" or not details.payment_intent_id:
        raise _SessionVerificationError("Checkout Session is not a completed payment.")
    if (
        quote.proposal_payment_intent_id is not None
        and quote.proposal_payment_intent_id != details.payment_intent_id
    ):
        raise _SessionVerificationError("PaymentIntent does not match this proposal.")
    return details.payment_intent_id


def _status(
    quote: Quote, choice: PaymentChoice, amount: Decimal, full: Decimal
) -> ProposalPaymentStatus:
    paid = quote.proposal_payment_paid_at is not None
    remaining = full - amount if choice == "fifty_percent_down" else Decimal("0")
    return ProposalPaymentStatus(
        payment_paid=paid,
        payment_required=not paid,
        payment_amount=float(amount),
        completion_balance=float(remaining),
        currency=quote.currency,
        payment_choice=choice,
    )


async def _reuse_existing_checkout(
    db: AsyncSession,
    quote: Quote,
    choice: PaymentChoice,
    amount: Decimal,
) -> ProposalPaymentCheckout | None:
    session_id = quote.proposal_payment_checkout_session_id
    if not session_id:
        return None
    try:
        details = await call_payment_service.retrieve_checkout_session_details(session_id)
        _validate_session_identity(quote, session_id, details, choice=choice, amount=amount)
        payment_intent_id = _paid_intent(quote, details)
    except _SessionVerificationError as exc:
        logger.warning(
            "proposal_payment_checkout_verification_failed",
            quote_id=str(quote.id),
            session_id=session_id,
            reason=str(exc),
        )
        raise ProposalPaymentError(
            "The existing payment link could not be verified. Please contact the business."
        ) from exc
    except Exception as exc:
        logger.warning(
            "proposal_payment_checkout_lookup_failed",
            quote_id=str(quote.id),
            session_id=session_id,
            error=str(exc),
        )
        raise ProposalPaymentError(
            "The payment link could not be checked. Please try again."
        ) from exc

    if payment_intent_id:
        await mark_proposal_payment_paid(
            db, quote, session_id=session_id, payment_intent_id=payment_intent_id
        )
        raise ProposalPaymentError("This proposal payment has already been received.")
    if details.status == "open":
        if not details.url:
            raise ProposalPaymentError("The payment link could not be opened. Please try again.")
        return ProposalPaymentCheckout(
            url=details.url,
            amount=float(amount),
            currency=quote.currency,
            payment_choice=choice,
        )
    if details.status == "complete":
        raise ProposalPaymentError("Payment is still processing. Please wait before trying again.")
    if details.status != "expired":
        raise ProposalPaymentError("The payment link has an unknown status. Please try again.")
    return None


async def create_proposal_payment_checkout_session(
    db: AsyncSession,
    token: str,
) -> ProposalPaymentCheckout:
    """Create or reuse the one active Checkout Session for an approved proposal."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.config import settings
    from app.models.quote import Quote
    from app.services.quotes.proposal_template import get_proposal_template

    if not call_payment_service.is_payment_configured():
        raise ProposalPaymentError("Online payment is not configured for this business.")

    result = await db.execute(
        select(Quote)
        .where(Quote.public_token == token)
        .options(selectinload(Quote.contact), selectinload(Quote.workspace))
        .with_for_update()
    )
    quote = result.scalar_one_or_none()
    if quote is None or quote.status == "draft":
        raise ProposalPaymentError("Proposal not found.")
    if not proposal_payments_enabled(quote):
        raise ProposalPaymentError("This proposal is not approved for online payment.")
    choice, amount, _full = _payment_state(quote)
    if quote.proposal_payment_paid_at is not None:
        raise ProposalPaymentError("This proposal payment has already been received.")

    existing_checkout = await _reuse_existing_checkout(db, quote, choice, amount)
    if existing_checkout is not None:
        return existing_checkout

    template = get_proposal_template(quote.workspace)
    business_name = template.business_name or (
        quote.workspace.name if quote.workspace else "Permanent Lighting"
    )
    product_name = (
        f"{business_name} — 50% payment for {quote.number}"
        if choice == "fifty_percent_down"
        else f"{business_name} — Payment in full for {quote.number}"
    )
    proposal_url = f"{settings.frontend_url}/p/quotes/{token}"
    try:
        session = await call_payment_service.create_payment_checkout_session(
            amount=amount,
            currency=quote.currency,
            product_name=product_name,
            metadata=_metadata(quote, choice),
            customer_email=quote.contact.email if quote.contact else None,
            success_url=f"{proposal_url}?payment=paid",
            cancel_url=f"{proposal_url}?payment=cancelled",
            idempotency_key=str(
                derive_outbound_key(
                    "proposal_payment_checkout",
                    quote.id,
                    choice,
                    quote.proposal_payment_checkout_session_id or "initial",
                )
            ),
        )
    except Exception as exc:
        logger.warning(
            "proposal_payment_checkout_create_failed",
            quote_id=str(quote.id),
            error=str(exc),
        )
        raise ProposalPaymentError("Could not start the payment. Please try again.") from exc
    if not session.url:
        raise ProposalPaymentError("Could not start the payment. Please try again.")

    quote.proposal_payment_checkout_session_id = session.session_id
    if session.payment_intent_id:
        quote.proposal_payment_intent_id = session.payment_intent_id
    await db.commit()
    logger.info(
        "proposal_payment_checkout_created",
        quote_id=str(quote.id),
        workspace_id=str(quote.workspace_id),
        payment_choice=choice,
        amount=float(amount),
        currency=quote.currency,
    )
    return ProposalPaymentCheckout(
        url=session.url,
        amount=float(amount),
        currency=quote.currency,
        payment_choice=choice,
    )


async def mark_proposal_payment_paid(
    db: AsyncSession,
    quote: Quote,
    *,
    session_id: str,
    payment_intent_id: str,
) -> bool:
    """Atomically record one verified provider payment; return whether this call won."""
    from sqlalchemy import or_, update

    from app.models.quote import Quote

    if quote.proposal_payment_paid_at is not None:
        return False
    paid_at = datetime.now(UTC)
    result = await db.execute(
        update(Quote)
        .where(
            Quote.id == quote.id,
            Quote.status == "approved",
            Quote.proposal_payment_paid_at.is_(None),
            Quote.proposal_payment_checkout_session_id == session_id,
            Quote.proposal_payment_choice == quote.proposal_payment_choice,
            Quote.proposal_payment_amount == quote.proposal_payment_amount,
            Quote.currency == quote.currency,
            or_(
                Quote.proposal_payment_intent_id.is_(None),
                Quote.proposal_payment_intent_id == payment_intent_id,
            ),
        )
        .values(
            proposal_payment_paid_at=paid_at,
            proposal_payment_intent_id=payment_intent_id,
        )
        .returning(Quote.id)
        .execution_options(synchronize_session=False)
    )
    transitioned = result.scalar_one_or_none() is not None
    await db.commit()
    await db.refresh(quote)
    if transitioned:
        logger.info(
            "proposal_payment_marked_paid",
            quote_id=str(quote.id),
            workspace_id=str(quote.workspace_id),
            payment_choice=quote.proposal_payment_choice,
        )
        await _notify_proposal_payment_paid(db, quote)
    return transitioned


async def _notify_proposal_payment_paid(db: AsyncSession, quote: Quote) -> None:
    """Notify operators once, after verified payment is durably recorded."""
    from app.models.contact import Contact
    from app.services.payments.customer_payment_notifications import (
        notify_customer_payment,
    )

    if quote.proposal_payment_amount is None:
        return
    contact = await db.get(Contact, quote.contact_id) if quote.contact_id is not None else None
    client_name = (
        " ".join(
            part
            for part in (
                contact.first_name if contact else None,
                contact.last_name if contact else None,
            )
            if part
        )
        or None
    )
    description = (
        f"50% down payment on {quote.number}"
        if quote.proposal_payment_choice == "fifty_percent_down"
        else f"Payment in full on {quote.number}"
    )
    try:
        await notify_customer_payment(
            db,
            workspace_id=quote.workspace_id,
            amount=quote.proposal_payment_amount,
            currency=quote.currency,
            description=description,
            idempotency_scope="proposal_payment_operator_email",
            idempotency_id=quote.id,
            deep_link="/(tabs)/quotes",
            client_name=client_name,
            client_email=contact.email if contact else None,
            client_phone=contact.phone_number if contact else None,
            quote_number=quote.number,
        )
    except Exception as exc:  # pragma: no cover - payment is already durable
        logger.warning("proposal_payment_notify_failed", quote_id=str(quote.id), error=str(exc))


async def reconcile_proposal_payment(db: AsyncSession, token: str) -> ProposalPaymentStatus:
    """Verify the stored Stripe Session on return and report current payment state."""
    from sqlalchemy import select

    from app.models.quote import Quote

    quote = (
        await db.execute(select(Quote).where(Quote.public_token == token))
    ).scalar_one_or_none()
    if quote is None or quote.status == "draft":
        raise ProposalPaymentError("Proposal not found.")
    choice, amount, full = _payment_state(quote)
    if quote.proposal_payment_paid_at is not None:
        return _status(quote, choice, amount, full)

    session_id = quote.proposal_payment_checkout_session_id
    if not session_id or not call_payment_service.is_payment_configured():
        return _status(quote, choice, amount, full)
    try:
        details = await call_payment_service.retrieve_checkout_session_details(session_id)
        _validate_session_identity(
            quote,
            session_id,
            details,
            choice=choice,
            amount=amount,
        )
        payment_intent_id = _paid_intent(quote, details)
    except _SessionVerificationError as exc:
        logger.warning(
            "proposal_payment_reconcile_rejected",
            quote_id=str(quote.id),
            session_id=session_id,
            reason=str(exc),
        )
        return _status(quote, choice, amount, full)
    except Exception as exc:
        logger.warning(
            "proposal_payment_reconcile_failed",
            quote_id=str(quote.id),
            session_id=session_id,
            error=str(exc),
        )
        return _status(quote, choice, amount, full)

    if payment_intent_id:
        await mark_proposal_payment_paid(
            db,
            quote,
            session_id=session_id,
            payment_intent_id=payment_intent_id,
        )
    return _status(quote, choice, amount, full)


def _event_details(session: Mapping[str, Any]) -> call_payment_service.CheckoutSessionDetails:
    metadata_raw = session.get("metadata")
    metadata = (
        {
            key: value
            for key, value in metadata_raw.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if isinstance(metadata_raw, Mapping)
        else {}
    )
    payment_intent_raw = session.get("payment_intent")
    payment_intent_id: str | None = None
    if isinstance(payment_intent_raw, str):
        payment_intent_id = payment_intent_raw
    elif isinstance(payment_intent_raw, Mapping):
        nested_id = payment_intent_raw.get("id")
        payment_intent_id = nested_id if isinstance(nested_id, str) else None
    amount_raw = session.get("amount_total")
    amount_total = (
        amount_raw if isinstance(amount_raw, int) and not isinstance(amount_raw, bool) else None
    )
    currency_raw = session.get("currency")
    url_raw = session.get("url")
    payment_status_raw = session.get("payment_status")
    status_raw = session.get("status")
    mode_raw = session.get("mode")
    return call_payment_service.CheckoutSessionDetails(
        payment_status=payment_status_raw if isinstance(payment_status_raw, str) else "",
        status=status_raw if isinstance(status_raw, str) else "",
        payment_intent_id=payment_intent_id,
        mode=mode_raw if isinstance(mode_raw, str) else "",
        metadata=metadata,
        amount_total=amount_total,
        currency=currency_raw.lower() if isinstance(currency_raw, str) else None,
        url=url_raw if isinstance(url_raw, str) else None,
    )


async def handle_proposal_payment_checkout_session_completed(
    session: dict[str, Any],
    db: AsyncSession,
) -> None:
    """Accept a signed Stripe event only when every stored payment field matches."""
    from sqlalchemy import select

    from app.models.quote import Quote

    details = _event_details(session)
    quote_id_raw = details.metadata.get("quote_id")
    workspace_id_raw = details.metadata.get("workspace_id")
    session_id = session.get("id")
    if (
        details.metadata.get("kind") != PROPOSAL_PAYMENT_KIND
        or not isinstance(session_id, str)
        or not quote_id_raw
        or not workspace_id_raw
    ):
        logger.warning("proposal_payment_webhook_missing_identity")
        return
    try:
        quote_id = uuid.UUID(quote_id_raw)
        workspace_id = uuid.UUID(workspace_id_raw)
    except ValueError:
        logger.warning("proposal_payment_webhook_invalid_identity")
        return

    quote = (
        await db.execute(
            select(Quote).where(Quote.id == quote_id, Quote.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    if quote is None:
        logger.warning(
            "proposal_payment_webhook_no_match",
            quote_id=quote_id_raw,
            workspace_id=workspace_id_raw,
            session_id=session_id,
        )
        return
    try:
        choice, amount, _full = _payment_state(quote)
        _validate_session_identity(
            quote,
            session_id,
            details,
            choice=choice,
            amount=amount,
        )
        payment_intent_id = _paid_intent(quote, details)
    except (ProposalPaymentError, _SessionVerificationError) as exc:
        logger.warning(
            "proposal_payment_webhook_rejected",
            quote_id=str(quote.id),
            session_id=session_id,
            reason=str(exc),
        )
        return
    if payment_intent_id is None:
        logger.info(
            "proposal_payment_webhook_not_paid",
            quote_id=str(quote.id),
            session_id=session_id,
        )
        return
    await mark_proposal_payment_paid(
        db,
        quote,
        session_id=session_id,
        payment_intent_id=payment_intent_id,
    )
