"""Customer invoice management endpoints.

Thin transport layer over :class:`app.services.invoices.InvoiceService`; all
domain rules (number allocation, total computation, derived status, void/delete
guards, payment reconciliation) live in the service. Access is capability-gated:
reads require ``billing:read`` and mutations ``billing:write`` (see
:mod:`app.core.permissions`); the gating dependency also resolves workspace
membership, so it replaces the old ``get_workspace`` access check. Line-item
mutations return the full invoice detail because they recompute the parent totals.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CanReadBilling, CanWriteBilling, CurrentUser
from app.api.service_errors import ServiceErrorRoute
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceDeliverRequest,
    InvoiceDeliverResult,
    InvoiceDetailResponse,
    InvoiceLineItemCreate,
    InvoiceLineItemUpdate,
    InvoicePaymentLinkResponse,
    InvoiceSendResponse,
    InvoiceUpdate,
    PaginatedInvoices,
    PublicInvoice,
    PublicInvoicePaymentCheckout,
    PublicInvoicePaymentRequest,
    PublicInvoicePaymentStatus,
)
from app.services.invoices import InvoiceService

router = APIRouter(route_class=ServiceErrorRoute)
# Customer-facing invoice page: no auth, addressed only by an unguessable token.
public_router = APIRouter(route_class=ServiceErrorRoute)


@router.get("", response_model=PaginatedInvoices)
async def list_invoices(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadBilling,
    invoice_status: Annotated[str | None, Query(alias="status")] = None,
    contact_id: Annotated[int | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> PaginatedInvoices:
    """List invoices in a workspace, newest first, with optional filters."""
    service = InvoiceService(db)
    return await service.list_invoices(
        workspace_id,
        page=page,
        page_size=page_size,
        status=invoice_status,
        contact_id=contact_id,
    )


@router.post("", response_model=InvoiceDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    workspace_id: uuid.UUID,
    invoice_in: InvoiceCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> InvoiceDetailResponse:
    """Create a draft invoice with its initial line items."""
    service = InvoiceService(db)
    return await service.create_invoice(workspace_id, invoice_in, created_by_id=current_user.id)


@router.get("/{invoice_id}", response_model=InvoiceDetailResponse)
async def get_invoice(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadBilling,
) -> InvoiceDetailResponse:
    """Get a specific invoice with its line items."""
    service = InvoiceService(db)
    return await service.get_invoice(workspace_id, invoice_id)


@router.put("/{invoice_id}", response_model=InvoiceDetailResponse)
async def update_invoice(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    invoice_in: InvoiceUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> InvoiceDetailResponse:
    """Update an invoice's header fields (totals/status are re-derived)."""
    service = InvoiceService(db)
    return await service.update_invoice(workspace_id, invoice_id, invoice_in)


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> None:
    """Delete a draft invoice. Issued invoices must be voided instead."""
    service = InvoiceService(db)
    await service.delete_invoice(workspace_id, invoice_id)


# Lifecycle transitions
@router.post("/{invoice_id}/deliver", response_model=InvoiceDeliverResult)
async def deliver_invoice(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    payload: InvoiceDeliverRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> InvoiceDeliverResult:
    """Send the customer their invoice link by email or SMS.

    Marks the invoice sent (allocating its share token) and delivers to the
    bill-to contact's email/phone, or an explicit ``to`` override. A rail that
    isn't ready (no destination, Telnyx unconfigured, opted out) fails with a
    message naming the fix.
    """
    service = InvoiceService(db)
    return await service.deliver_invoice(
        workspace_id, invoice_id, channel=payload.channel, to=payload.to
    )


@router.post("/{invoice_id}/send", response_model=InvoiceSendResponse)
async def send_invoice(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> InvoiceSendResponse:
    """Mark an invoice as sent and email it to the bill-to contact.

    ``delivery`` reports whether the customer was actually emailed: an invoice
    with no bill-to contact still transitions to ``sent`` but returns
    ``skipped_no_email`` so the UI can say so instead of claiming success.
    """
    service = InvoiceService(db)
    return await service.mark_sent(workspace_id, invoice_id)


@router.post("/{invoice_id}/void", response_model=InvoiceDetailResponse)
async def void_invoice(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> InvoiceDetailResponse:
    """Void an invoice. Fully paid invoices cannot be voided."""
    service = InvoiceService(db)
    return await service.void_invoice(workspace_id, invoice_id)


@router.post("/{invoice_id}/payment-link", response_model=InvoicePaymentLinkResponse)
async def create_payment_link(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> InvoicePaymentLinkResponse:
    """Create a Stripe Checkout link for the invoice's outstanding balance."""
    service = InvoiceService(db)
    session_id, url = await service.create_payment_link(workspace_id, invoice_id)
    return InvoicePaymentLinkResponse(session_id=session_id, url=url)


# Line-item sub-resource. Mutations return the full invoice because totals change.
@router.post(
    "/{invoice_id}/line-items",
    response_model=InvoiceDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_line_item(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    item_in: InvoiceLineItemCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> InvoiceDetailResponse:
    """Add a line item and recompute invoice totals."""
    service = InvoiceService(db)
    return await service.add_line_item(workspace_id, invoice_id, item_in)


@router.put("/{invoice_id}/line-items/{item_id}", response_model=InvoiceDetailResponse)
async def update_line_item(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    item_id: uuid.UUID,
    item_in: InvoiceLineItemUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> InvoiceDetailResponse:
    """Update a line item and recompute invoice totals."""
    service = InvoiceService(db)
    return await service.update_line_item(workspace_id, invoice_id, item_id, item_in)


@router.delete(
    "/{invoice_id}/line-items/{item_id}",
    response_model=InvoiceDetailResponse,
)
async def remove_line_item(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> InvoiceDetailResponse:
    """Remove a line item and recompute invoice totals."""
    service = InvoiceService(db)
    return await service.remove_line_item(workspace_id, invoice_id, item_id)


# ---------------------------------------------------------------------------
# Public customer invoice (no auth, token-keyed)
# ---------------------------------------------------------------------------
@public_router.get("/{token}", response_model=PublicInvoice)
async def get_public_invoice(token: str, db: DB) -> PublicInvoice:
    """Render a customer's invoice from its share token. Drafts/unknown 404."""
    return await InvoiceService(db).get_public_invoice(token)


@public_router.post("/{token}/pay", response_model=PublicInvoicePaymentCheckout)
async def create_public_invoice_payment(
    token: str,
    db: DB,
    payload: PublicInvoicePaymentRequest | None = None,
) -> PublicInvoicePaymentCheckout:
    """Start a server-priced Stripe Checkout Session for the selected rows.

    The body contains optional row UUIDs only. Required rows are always charged.
    An omitted body preserves the current selection for rollout compatibility.
    """
    selected_ids = None if payload is None else payload.selected_optional_line_item_ids
    return await InvoiceService(db).create_public_payment_checkout(token, selected_ids)


@public_router.post("/{token}/payment-status", response_model=PublicInvoicePaymentStatus)
async def reconcile_public_invoice_payment(token: str, db: DB) -> PublicInvoicePaymentStatus:
    """Reconcile the invoice against Stripe on return from checkout.

    A webhook backstop so a delayed or dropped webhook never leaves a paid
    invoice reading unpaid. Idempotent.
    """
    return await InvoiceService(db).reconcile_public_payment(token)
