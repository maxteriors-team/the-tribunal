"""Card-on-file endpoints: the operator's side of a saved card.

Two surfaces exist for card-on-file and only one of them is here. The **customer**
types their own card into a Stripe-hosted iframe behind a tokenized public link
(``/p/card-setup/{token}``, in :mod:`app.api.v1.card_setup`). This router is what
the operator gets: see the cards a contact has saved, send them a link to add
one, remove one, choose the default, and charge one.

There is deliberately no endpoint here that accepts card details. An operator
typing a customer's card into the dashboard would be a card-not-present
transaction with worse decline rates, higher fraud exposure, and a consent record
that is the operator clicking a box on the customer's behalf. Sending the link is
the whole job.

Access is capability-gated: reads need ``billing:read`` and anything that moves
money or changes a stored card needs ``billing:write``.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import DB, CanReadBilling, CanWriteBilling, CurrentUser
from app.api.service_errors import ServiceErrorRoute
from app.core.config import settings
from app.db.scope import assert_workspace_owned
from app.models.contact import Contact
from app.schemas.payment_method import (
    CardSetupLinkResponse,
    ChargeCardRequest,
    ChargeCardResponse,
    PaymentMethodResponse,
)
from app.services.payments import card_on_file_service

router = APIRouter(route_class=ServiceErrorRoute)


@router.get("", response_model=list[PaymentMethodResponse])
async def list_payment_methods(
    workspace_id: uuid.UUID,
    contact_id: int,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadBilling,
) -> list[PaymentMethodResponse]:
    """List the cards this contact has authorised us to keep, default first."""
    await assert_workspace_owned(db, Contact, contact_id, workspace_id, detail="Contact not found")
    methods = await card_on_file_service.list_payment_methods(
        db, workspace_id=workspace_id, contact_id=contact_id
    )
    return [PaymentMethodResponse.model_validate(m) for m in methods]


@router.post(
    "/setup-link",
    response_model=CardSetupLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_setup_link(
    workspace_id: uuid.UUID,
    contact_id: int,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> CardSetupLinkResponse:
    """Mint a single-use, 72-hour link the customer opens to save their card.

    Minting a new link invalidates any earlier unused one for the same contact,
    so "send it again" never leaves two live card-entry URLs for one customer.
    """
    await assert_workspace_owned(db, Contact, contact_id, workspace_id, detail="Contact not found")
    token = await card_on_file_service.mint_card_setup_token(
        db,
        workspace_id=workspace_id,
        contact_id=contact_id,
        created_by_id=current_user.id,
    )
    return CardSetupLinkResponse(
        url=f"{settings.frontend_url.rstrip('/')}/p/card-setup/{token.token}",
        token=token.token,
        expires_at=token.expires_at,
    )


@router.post("/{payment_method_id}/default", response_model=PaymentMethodResponse)
async def set_default_payment_method(
    workspace_id: uuid.UUID,
    contact_id: int,
    payment_method_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> PaymentMethodResponse:
    """Choose which saved card automatic charges use."""
    method = await card_on_file_service.set_default_payment_method(
        db,
        workspace_id=workspace_id,
        contact_id=contact_id,
        payment_method_id=payment_method_id,
    )
    return PaymentMethodResponse.model_validate(method)


@router.delete("/{payment_method_id}", response_model=PaymentMethodResponse)
async def remove_payment_method(
    workspace_id: uuid.UUID,
    contact_id: int,
    payment_method_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> PaymentMethodResponse:
    """Forget a saved card: detached at Stripe, marked removed here.

    A soft delete. The row stays because charge attempts point at it and those
    are the record of money already taken, but the card can no longer be charged.
    """
    method = await card_on_file_service.remove_payment_method(
        db,
        workspace_id=workspace_id,
        contact_id=contact_id,
        payment_method_id=payment_method_id,
    )
    return PaymentMethodResponse.model_validate(method)


@router.post("/charge", response_model=ChargeCardResponse)
async def charge_card_on_file(
    workspace_id: uuid.UUID,
    contact_id: int,
    payload: ChargeCardRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> ChargeCardResponse:
    """Charge this contact's saved card for a stated amount.

    An explicit operator action, so it is **not** suppressed by the
    ``no-automation`` tag — that tag mutes automation, not the human.

    The idempotency key is derived from the operator, the contact, the amount and
    the invoice, so a double-clicked button charges once. A different amount, or
    a later deliberate re-charge of the same amount, produces a different key and
    is allowed through — this dedupes accidents, not intent.

    Never raises for a declined card: the outcome is in ``status``.
    """
    await assert_workspace_owned(db, Contact, contact_id, workspace_id, detail="Contact not found")
    from app.services.idempotency import derive_outbound_key

    idempotency_key = str(
        derive_outbound_key(
            "card_on_file_manual_charge",
            workspace_id,
            contact_id,
            current_user.id,
            f"{payload.amount:.2f}",
            payload.currency.upper(),
            payload.invoice_id or "",
        )
    )
    result = await card_on_file_service.charge_saved_card(
        db,
        workspace_id=workspace_id,
        contact_id=contact_id,
        amount=payload.amount,
        currency=payload.currency.upper(),
        description=payload.description,
        trigger=payload.trigger,
        idempotency_key=idempotency_key,
        automated=False,
        invoice_id=payload.invoice_id,
        payment_method_id=payload.payment_method_id,
    )

    if result.succeeded and payload.invoice_id is not None:
        await _apply_to_invoice(db, workspace_id, payload.invoice_id, result)

    # ``client_secret`` is deliberately dropped here: it stays server-side, and
    # the customer is recovered through ``recovery_url`` instead.
    return ChargeCardResponse(
        status=result.status,  # type: ignore[arg-type]
        amount=result.amount,
        currency=result.currency,
        attempt_id=result.attempt_id,
        payment_intent_id=result.payment_intent_id,
        decline_code=result.decline_code,
        message=result.message,
        recovery_url=result.recovery_url,
    )


async def _apply_to_invoice(
    db: DB,
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    result: card_on_file_service.ChargeResult,
) -> None:
    """Credit a successful card-on-file charge against its invoice.

    Routed through ``InvoiceService.record_payment`` rather than touching
    ``amount_paid`` directly, so a card-on-file payment derives status, fires the
    ``invoice.paid`` automation event, and notifies the operator on exactly the
    same path as a customer paying online. ``record_payment`` is idempotent on
    the payment-intent id, so a replayed charge cannot double-credit.
    """
    from app.api.crud import get_or_404
    from app.models.invoice import Invoice
    from app.services.invoices import InvoiceService

    invoice = await get_or_404(db, Invoice, invoice_id, workspace_id=workspace_id)
    await InvoiceService(db).record_payment(
        invoice,
        result.amount,
        payment_intent_id=result.payment_intent_id,
    )
