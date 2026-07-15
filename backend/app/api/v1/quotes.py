"""Quote (estimate) management endpoints.

Thin transport layer over :class:`app.services.quotes.QuoteService`; all domain
rules (number allocation, total computation, lifecycle guards, expiry, and
conversion to job/invoice) live in the service. Access is capability-gated:
reads require ``billing:read`` and mutations ``billing:write`` (see
:mod:`app.core.permissions`); the gating dependency also resolves workspace
membership, replacing the old ``get_workspace`` access check. Line-item
mutations return the full quote detail because they recompute the parent totals.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DB, CanReadBilling, CanWriteBilling, CurrentUser
from app.api.service_errors import ServiceErrorRoute
from app.schemas.estimate import (
    ComparisonDeliverRequest,
    ComparisonDeliverResult,
    ComparisonShareRequest,
    ComparisonShareResult,
    LinearFeetEstimateRequest,
    LinearFeetEstimateResult,
    PublicComparison,
)
from app.schemas.proposal import (
    PublicProposal,
    PublicProposalActionResult,
    PublicProposalDecline,
    PublicProposalDepositCheckout,
    PublicProposalDepositStatus,
)
from app.schemas.proposal_wizard import ProposalDocument, ProposalWizardPayload
from app.schemas.quote import (
    PaginatedQuotes,
    QuoteConvertRequest,
    QuoteConvertResponse,
    QuoteCreate,
    QuoteDeclineRequest,
    QuoteDeliverRequest,
    QuoteDeliverResult,
    QuoteDetailResponse,
    QuoteLineItemCreate,
    QuoteLineItemUpdate,
    QuoteUpdate,
)
from app.services.quotes import QuoteService

router = APIRouter(route_class=ServiceErrorRoute)
# No-auth, token-keyed client proposal surface. Uses ServiceErrorRoute so the
# service's NotFoundError/ConflictError map to 404/409 at the boundary.
public_router = APIRouter(route_class=ServiceErrorRoute)
# No-auth, token-keyed permanent-vs-temporary comparison surface (mounted at
# ``/p/compare``). Deliberately separate so the client payload never carries the
# internal linear-feet measurement.
comparison_public_router = APIRouter(route_class=ServiceErrorRoute)


@router.get("", response_model=PaginatedQuotes)
async def list_quotes(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadBilling,
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
    membership: CanWriteBilling,
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
    membership: CanReadBilling,
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
    membership: CanWriteBilling,
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
    membership: CanWriteBilling,
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
    membership: CanWriteBilling,
) -> QuoteDetailResponse:
    """Mark a quote as sent and email it to the quote-to contact."""
    service = QuoteService(db)
    return await service.mark_sent(workspace_id, quote_id)


@router.post("/{quote_id}/deliver", response_model=QuoteDeliverResult)
async def deliver_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: QuoteDeliverRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> QuoteDeliverResult:
    """Send the client proposal link by email or SMS.

    Marks the quote sent (allocating its share token) and delivers the link to
    the wizard snapshot's client email/phone, the linked contact's, or an
    explicit ``to`` override.
    """
    service = QuoteService(db)
    return await service.deliver_quote(
        workspace_id, quote_id, channel=payload.channel, to=payload.to
    )


@router.post("/{quote_id}/approve", response_model=QuoteDetailResponse)
async def approve_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
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
    membership: CanWriteBilling,
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
    membership: CanWriteBilling,
) -> QuoteConvertResponse:
    """Convert an approved quote into a scheduled job and/or an invoice."""
    service = QuoteService(db)
    return await service.convert_quote(
        workspace_id,
        quote_id,
        create_job=payload.create_job,
        create_invoice=payload.create_invoice,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_end,
    )


# Sales wizard: config-driven multi-tier proposal builder. Preview computes the
# document without persisting; save materializes a draft quote (server-recomputed
# headline-tier line items) plus the rich snapshot on ``proposal_document``.
@router.post("/wizard/preview", response_model=ProposalDocument)
async def preview_wizard_proposal(
    workspace_id: uuid.UUID,
    payload: ProposalWizardPayload,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadBilling,
) -> ProposalDocument:
    """Compute the full multi-tier proposal document without saving."""
    service = QuoteService(db)
    return await service.preview_from_wizard(workspace_id, payload)


@router.post(
    "/wizard",
    response_model=QuoteDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_wizard_proposal(
    workspace_id: uuid.UUID,
    payload: ProposalWizardPayload,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> QuoteDetailResponse:
    """Save a wizard proposal as a draft quote + its multi-tier snapshot."""
    service = QuoteService(db)
    return await service.save_from_wizard(workspace_id, payload, created_by_id=current_user.id)


# Roofline estimator: price permanent vs seasonal for a measured linear-feet
# figure. Feet is the only client input; every dollar is server-computed.
@router.post("/estimate", response_model=LinearFeetEstimateResult)
async def estimate_linear_feet(
    workspace_id: uuid.UUID,
    payload: LinearFeetEstimateRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadBilling,
) -> LinearFeetEstimateResult:
    """Compute a permanent-vs-temporary estimate for a measured roofline."""
    service = QuoteService(db)
    return await service.estimate_linear_feet(workspace_id, payload)


@router.post(
    "/estimate/share",
    response_model=ComparisonShareResult,
    status_code=status.HTTP_201_CREATED,
)
async def share_comparison(
    workspace_id: uuid.UUID,
    payload: ComparisonShareRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> ComparisonShareResult:
    """Persist a comparison behind a token and return the client-facing link."""
    service = QuoteService(db)
    return await service.share_comparison(workspace_id, payload, created_by_id=current_user.id)


@router.post(
    "/estimate/comparison/{token}/send",
    response_model=ComparisonDeliverResult,
)
async def deliver_comparison(
    workspace_id: uuid.UUID,
    token: str,
    payload: ComparisonDeliverRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> ComparisonDeliverResult:
    """Email a saved estimate's client link to the customer."""
    service = QuoteService(db)
    return await service.deliver_comparison(workspace_id, token, to=payload.to)


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
    membership: CanWriteBilling,
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
    membership: CanWriteBilling,
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
    membership: CanWriteBilling,
) -> QuoteDetailResponse:
    """Remove a line item and recompute quote totals."""
    service = QuoteService(db)
    return await service.remove_line_item(workspace_id, quote_id, item_id)


# ---------------------------------------------------------------------------
# Public client proposal (no auth, token-keyed)
# ---------------------------------------------------------------------------
@public_router.get("/{token}", response_model=PublicProposal)
async def get_public_proposal(token: str, db: DB) -> PublicProposal:
    """Render a client's proposal from its share token. Drafts/unknown 404."""
    return await QuoteService(db).get_public_proposal(token)


@public_router.post("/{token}/approve", response_model=PublicProposalActionResult)
async def approve_public_proposal(token: str, db: DB) -> PublicProposalActionResult:
    """Client approves their proposal (idempotent; expired/declined rejected)."""
    return await QuoteService(db).approve_public(token)


@public_router.post("/{token}/decline", response_model=PublicProposalActionResult)
async def decline_public_proposal(
    token: str,
    payload: PublicProposalDecline,
    db: DB,
) -> PublicProposalActionResult:
    """Client declines their proposal with an optional reason (idempotent)."""
    return await QuoteService(db).decline_public(token, reason=payload.reason)


@public_router.post("/{token}/deposit-checkout", response_model=PublicProposalDepositCheckout)
async def create_deposit_checkout(token: str, db: DB) -> PublicProposalDepositCheckout:
    """Start a Stripe Checkout Session so the client can pay the deposit.

    Returns the hosted payment URL for the frontend to redirect to. A bad state
    (no deposit due, already paid, expired/declined, or Stripe unconfigured)
    surfaces as a 400 with a client-safe message.
    """
    from app.services.payments.quote_deposit_service import (
        DepositError,
        create_deposit_checkout_session,
    )

    try:
        checkout = await create_deposit_checkout_session(db, token)
    except DepositError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PublicProposalDepositCheckout(
        url=checkout.url, amount=checkout.amount, currency=checkout.currency
    )


@public_router.post("/{token}/deposit-status", response_model=PublicProposalDepositStatus)
async def reconcile_deposit_status(token: str, db: DB) -> PublicProposalDepositStatus:
    """Reconcile a proposal's deposit against Stripe on return from checkout.

    A webhook backstop: verifies the stored Checkout Session and marks the
    deposit paid if Stripe confirms it, so a delayed/absent webhook never leaves
    a paid deposit showing unpaid. Idempotent.
    """
    from app.services.payments.quote_deposit_service import (
        DepositError,
        reconcile_deposit,
    )

    try:
        status_result = await reconcile_deposit(db, token)
    except DepositError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PublicProposalDepositStatus(
        deposit_paid=status_result.deposit_paid,
        deposit_amount=status_result.deposit_amount,
        currency=status_result.currency,
    )


# ---------------------------------------------------------------------------
# Public permanent-vs-temporary comparison (no auth, token-keyed)
# ---------------------------------------------------------------------------
@comparison_public_router.get("/{token}", response_model=PublicComparison)
async def get_public_comparison(token: str, db: DB) -> PublicComparison:
    """Render a client's permanent-vs-temporary savings comparison by token.

    Prices are recomputed from the workspace's live pricing config; the payload
    never includes the internal linear-feet measurement. Unknown tokens 404.
    """
    return await QuoteService(db).get_public_comparison(token)
