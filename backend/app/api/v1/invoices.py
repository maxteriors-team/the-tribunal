"""Customer invoice management endpoints.

Thin transport layer over :class:`app.services.invoices.InvoiceService`; all
domain rules (number allocation, total computation, derived status, void/delete
guards, payment reconciliation) live in the service. Workspace scoping and auth
follow the same deps as ``opportunities.py``. Line-item mutations return the full
invoice detail because they recompute the parent totals.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DB, CurrentUser, get_workspace
from app.api.service_errors import ServiceErrorRoute
from app.models.workspace import Workspace
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceDetailResponse,
    InvoiceLineItemCreate,
    InvoiceLineItemUpdate,
    InvoicePaymentLinkResponse,
    InvoiceUpdate,
    PaginatedInvoices,
)
from app.services.invoices import InvoiceService

router = APIRouter(route_class=ServiceErrorRoute)


@router.get("", response_model=PaginatedInvoices)
async def list_invoices(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
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
    workspace: Annotated[Workspace, Depends(get_workspace)],
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
    workspace: Annotated[Workspace, Depends(get_workspace)],
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
    workspace: Annotated[Workspace, Depends(get_workspace)],
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
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a draft invoice. Issued invoices must be voided instead."""
    service = InvoiceService(db)
    await service.delete_invoice(workspace_id, invoice_id)


# Lifecycle transitions
@router.post("/{invoice_id}/send", response_model=InvoiceDetailResponse)
async def send_invoice(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> InvoiceDetailResponse:
    """Mark an invoice as sent (email delivery is wired in a later phase)."""
    service = InvoiceService(db)
    return await service.mark_sent(workspace_id, invoice_id)


@router.post("/{invoice_id}/void", response_model=InvoiceDetailResponse)
async def void_invoice(
    workspace_id: uuid.UUID,
    invoice_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
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
    workspace: Annotated[Workspace, Depends(get_workspace)],
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
    workspace: Annotated[Workspace, Depends(get_workspace)],
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
    workspace: Annotated[Workspace, Depends(get_workspace)],
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
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> InvoiceDetailResponse:
    """Remove a line item and recompute invoice totals."""
    service = InvoiceService(db)
    return await service.remove_line_item(workspace_id, invoice_id, item_id)
