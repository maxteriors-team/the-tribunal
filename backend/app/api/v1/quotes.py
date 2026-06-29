"""Quote (estimate) management endpoints.

Thin transport layer over :class:`app.services.quotes.QuoteService`; all domain
rules (number allocation, total computation, lifecycle guards, expiry, and
conversion to job/invoice) live in the service. Workspace scoping and auth
follow the same deps as ``invoices.py``. Line-item mutations return the full
quote detail because they recompute the parent totals.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DB, CurrentUser, get_workspace
from app.api.service_errors import ServiceErrorRoute
from app.models.workspace import Workspace
from app.schemas.quote import (
    PaginatedQuotes,
    QuoteConvertRequest,
    QuoteConvertResponse,
    QuoteCreate,
    QuoteDeclineRequest,
    QuoteDetailResponse,
    QuoteLineItemCreate,
    QuoteLineItemUpdate,
    QuoteUpdate,
)
from app.services.quotes import QuoteService

router = APIRouter(route_class=ServiceErrorRoute)


@router.get("", response_model=PaginatedQuotes)
async def list_quotes(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    quote_status: Annotated[str | None, Query(alias="status")] = None,
    contact_id: Annotated[int | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> PaginatedQuotes:
    """List quotes in a workspace, newest first, with optional filters."""
    service = QuoteService(db)
    return await service.list_quotes(
        workspace_id,
        page=page,
        page_size=page_size,
        status=quote_status,
        contact_id=contact_id,
    )


@router.post("", response_model=QuoteDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_quote(
    workspace_id: uuid.UUID,
    quote_in: QuoteCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> QuoteDetailResponse:
    """Create a draft quote with its initial line items."""
    service = QuoteService(db)
    return await service.create_quote(workspace_id, quote_in, created_by_id=current_user.id)


@router.get("/{quote_id}", response_model=QuoteDetailResponse)
async def get_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> QuoteDetailResponse:
    """Get a specific quote with its line items."""
    service = QuoteService(db)
    return await service.get_quote(workspace_id, quote_id)


@router.put("/{quote_id}", response_model=QuoteDetailResponse)
async def update_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    quote_in: QuoteUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> QuoteDetailResponse:
    """Update a quote's header fields (totals are re-derived)."""
    service = QuoteService(db)
    return await service.update_quote(workspace_id, quote_id, quote_in)


@router.delete("/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a draft/sent quote. Decided or expired quotes are kept."""
    service = QuoteService(db)
    await service.delete_quote(workspace_id, quote_id)


# Lifecycle transitions
@router.post("/{quote_id}/send", response_model=QuoteDetailResponse)
async def send_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> QuoteDetailResponse:
    """Mark a quote as sent and email it to the quote-to contact."""
    service = QuoteService(db)
    return await service.mark_sent(workspace_id, quote_id)


@router.post("/{quote_id}/approve", response_model=QuoteDetailResponse)
async def approve_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> QuoteDetailResponse:
    """Operator approves a quote on the customer's behalf."""
    service = QuoteService(db)
    return await service.approve_quote(workspace_id, quote_id)


@router.post("/{quote_id}/decline", response_model=QuoteDetailResponse)
async def decline_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: QuoteDeclineRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> QuoteDetailResponse:
    """Operator declines a quote on the customer's behalf."""
    service = QuoteService(db)
    return await service.decline_quote(workspace_id, quote_id, reason=payload.reason)


@router.post("/{quote_id}/convert", response_model=QuoteConvertResponse)
async def convert_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: QuoteConvertRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> QuoteConvertResponse:
    """Convert an approved quote into a scheduled job and/or an invoice."""
    service = QuoteService(db)
    return await service.convert_quote(
        workspace_id,
        quote_id,
        create_job=payload.create_job,
        create_invoice=payload.create_invoice,
    )


# Line-item sub-resource. Mutations return the full quote because totals change.
@router.post(
    "/{quote_id}/line-items",
    response_model=QuoteDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_line_item(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    item_in: QuoteLineItemCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> QuoteDetailResponse:
    """Add a line item and recompute quote totals."""
    service = QuoteService(db)
    return await service.add_line_item(workspace_id, quote_id, item_in)


@router.put("/{quote_id}/line-items/{item_id}", response_model=QuoteDetailResponse)
async def update_line_item(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    item_id: uuid.UUID,
    item_in: QuoteLineItemUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> QuoteDetailResponse:
    """Update a line item and recompute quote totals."""
    service = QuoteService(db)
    return await service.update_line_item(workspace_id, quote_id, item_id, item_in)


@router.delete(
    "/{quote_id}/line-items/{item_id}",
    response_model=QuoteDetailResponse,
)
async def remove_line_item(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> QuoteDetailResponse:
    """Remove a line item and recompute quote totals."""
    service = QuoteService(db)
    return await service.remove_line_item(workspace_id, quote_id, item_id)
