"""Quote (estimate) management endpoints.

Thin transport layer over :class:`app.services.quotes.QuoteService`; all domain
rules (number allocation, total computation, lifecycle guards, expiry, and
conversion to job/invoice) live in the service. Ordinary quote access uses the
dedicated ``quotes:read/write`` capabilities. Reassignment, invoice creation,
and paid rendering remain ``billing:write`` operations; sales reps may record
offline deposits and schedule jobs only from their own quotes.
"""

import uuid
from datetime import UTC
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from app.api.deps import (
    DB,
    CanReadQuotes,
    CanWriteBilling,
    CanWriteQuotes,
    CurrentUser,
)
from app.api.service_errors import ServiceErrorRoute
from app.api.v1.contact_attachments import content_disposition, sanitize_filename
from app.core.permissions import Capability, quote_owner_scope, role_can
from app.models.quote import Quote
from app.models.quote_handoff_image import (
    MAX_HANDOFF_IMAGE_BYTES,
    MAX_HANDOFF_IMAGES_PER_QUOTE,
    QuoteHandoffImage,
)
from app.schemas.estimate import (
    ComparisonDeliverRequest,
    ComparisonDeliverResult,
    ComparisonShareRequest,
    ComparisonShareResult,
    EstimateQuoteRequest,
    EstimateRenderRequest,
    EstimateRenderResult,
    LinearFeetEstimateRequest,
    LinearFeetEstimateResult,
    PublicComparison,
    PublicComparisonDecline,
    PublicComparisonDeclineResult,
)
from app.schemas.handoff_image import HandoffImageListResponse, HandoffImageResponse
from app.schemas.inventory import QuoteInventoryAvailabilityResponse
from app.schemas.proposal import (
    PublicProposal,
    PublicProposalActionResult,
    PublicProposalApprove,
    PublicProposalDecline,
    PublicProposalDepositCheckout,
    PublicProposalDepositStatus,
)
from app.schemas.proposal_wizard import ProposalDocument, ProposalWizardPayload
from app.schemas.quote import (
    CrewNotificationResult,
    PaginatedQuotes,
    QuoteAssignmentRequest,
    QuoteConvertRequest,
    QuoteConvertResponse,
    QuoteCreate,
    QuoteDeclineRequest,
    QuoteDeliverRequest,
    QuoteDeliverResult,
    QuoteDepositRecordRequest,
    QuoteDetailResponse,
    QuoteLineItemCreate,
    QuoteLineItemUpdate,
    QuoteServiceCreate,
    QuoteUpdate,
)
from app.services.idempotency import (
    redis_idempotency_key_exists,
    set_redis_idempotency_key,
)
from app.services.inventory import QuoteInventoryAvailabilityService
from app.services.jobs import JobService
from app.services.notifications import notify_workspace_event
from app.services.payments.quote_deposit_service import record_manual_deposit
from app.services.quotes import QuoteService
from app.services.quotes.ownership import quote_owner_predicate
from app.services.quotes.proposal_pricing import BistroPricingConfigurationError

logger = structlog.get_logger(__name__)
router = APIRouter(route_class=ServiceErrorRoute)
# No-auth, token-keyed client proposal surface. Uses ServiceErrorRoute so the
# service's NotFoundError/ConflictError map to 404/409 at the boundary.
public_router = APIRouter(route_class=ServiceErrorRoute)
# No-auth, token-keyed permanent-vs-temporary comparison surface (mounted at
# ``/p/compare``). Deliberately separate so the client payload never carries the
# internal linear-feet measurement.
comparison_public_router = APIRouter(route_class=ServiceErrorRoute)


async def _scoped_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    current_user: CurrentUser,
    membership: CanReadQuotes,
    db: DB,
) -> Quote:
    """Load a quote only when the caller may access its owner scope."""
    owner_user_id = quote_owner_scope(membership.role, current_user.id)
    query = select(Quote).where(
        Quote.id == quote_id,
        Quote.workspace_id == workspace_id,
        quote_owner_predicate(owner_user_id),
    )
    quote = (await db.execute(query)).scalar_one_or_none()
    if quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
    return quote


ScopedQuote = Annotated[Quote, Depends(_scoped_quote)]

_HANDOFF_IMAGE_METADATA_COLUMNS = (
    QuoteHandoffImage.id,
    QuoteHandoffImage.filename,
    QuoteHandoffImage.content_type,
    QuoteHandoffImage.size_bytes,
    QuoteHandoffImage.created_at,
)


def _detect_handoff_image_type(data: bytes) -> str | None:
    """Return the canonical MIME type for supported image signatures."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("", response_model=PaginatedQuotes)
async def list_quotes(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadQuotes,
    quote_status: Annotated[str | None, Query(alias="status")] = None,
    contact_id: Annotated[int | None, Query()] = None,
    assigned_user_id: Annotated[int | None, Query()] = None,
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
        assigned_user_id=assigned_user_id,
        owner_user_id=quote_owner_scope(membership.role, current_user.id),
    )


@router.post("", response_model=QuoteDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_quote(
    workspace_id: uuid.UUID,
    quote_in: QuoteCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Create a draft quote with its initial line items."""
    service = QuoteService(db)
    return await service.create_quote(
        workspace_id,
        quote_in,
        created_by_id=current_user.id,
        assigned_user_id=quote_owner_scope(membership.role, current_user.id),
    )


@router.get("/{quote_id}", response_model=QuoteDetailResponse)
async def get_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadQuotes,
) -> QuoteDetailResponse:
    """Get a specific quote with its line items."""
    service = QuoteService(db)
    return await service.get_quote(workspace_id, quote_id)


@router.get("/{quote_id}/handoff-images", response_model=HandoffImageListResponse)
async def list_quote_handoff_images(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    _quote: ScopedQuote,
    db: DB,
) -> HandoffImageListResponse:
    """List field-team image metadata without loading the stored bytes."""
    rows = (
        (
            await db.execute(
                select(QuoteHandoffImage)
                .options(load_only(*_HANDOFF_IMAGE_METADATA_COLUMNS))
                .where(
                    QuoteHandoffImage.workspace_id == _quote.workspace_id,
                    QuoteHandoffImage.quote_id == _quote.id,
                )
                .order_by(QuoteHandoffImage.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return HandoffImageListResponse(
        images=[HandoffImageResponse.model_validate(row) for row in rows],
        max_images=MAX_HANDOFF_IMAGES_PER_QUOTE,
        max_image_bytes=MAX_HANDOFF_IMAGE_BYTES,
    )


@router.post(
    "/{quote_id}/handoff-images",
    response_model=HandoffImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_quote_handoff_image(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    file: UploadFile,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteQuotes,
) -> HandoffImageResponse:
    """Store one validated handoff image for the authorized quote."""
    data = await file.read(MAX_HANDOFF_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploaded image is empty",
        )
    if len(data) > MAX_HANDOFF_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Image exceeds the {MAX_HANDOFF_IMAGE_BYTES // (1024 * 1024)} MB limit",
        )

    detected_type = _detect_handoff_image_type(data)
    if detected_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Use a JPEG, PNG, or WebP image",
        )
    if (file.content_type or "").lower() != detected_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Declared image type does not match file contents",
        )

    locked_quote_id = (
        await db.execute(
            select(Quote.id)
            .where(
                Quote.id == _quote.id,
                Quote.workspace_id == _quote.workspace_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if locked_quote_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")

    image_count = await db.scalar(
        select(func.count(QuoteHandoffImage.id)).where(
            QuoteHandoffImage.workspace_id == _quote.workspace_id,
            QuoteHandoffImage.quote_id == _quote.id,
        )
    )
    if (image_count or 0) >= MAX_HANDOFF_IMAGES_PER_QUOTE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A quote can have at most {MAX_HANDOFF_IMAGES_PER_QUOTE} handoff images",
        )

    image = QuoteHandoffImage(
        workspace_id=_quote.workspace_id,
        quote_id=_quote.id,
        filename=sanitize_filename(file.filename),
        content_type=detected_type,
        size_bytes=len(data),
        data=data,
        uploaded_by_user_id=current_user.id,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    logger.info(
        "quote_handoff_image_uploaded",
        workspace_id=str(_quote.workspace_id),
        quote_id=str(_quote.id),
        image_id=str(image.id),
        size_bytes=image.size_bytes,
    )
    return HandoffImageResponse.model_validate(image)


@router.get("/{quote_id}/handoff-images/{image_id}/download")
async def download_quote_handoff_image(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    image_id: uuid.UUID,
    _quote: ScopedQuote,
    db: DB,
) -> Response:
    """Serve one authorized image inline using its detected content type."""
    image = (
        await db.execute(
            select(QuoteHandoffImage).where(
                QuoteHandoffImage.id == image_id,
                QuoteHandoffImage.workspace_id == _quote.workspace_id,
                QuoteHandoffImage.quote_id == _quote.id,
            )
        )
    ).scalar_one_or_none()
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Handoff image not found",
        )
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={
            "Content-Disposition": content_disposition(image.filename, image.content_type),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete(
    "/{quote_id}/handoff-images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_quote_handoff_image(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    image_id: uuid.UUID,
    _quote: ScopedQuote,
    db: DB,
    _gate: CanWriteQuotes,
) -> None:
    """Delete one image only from its authorized workspace and quote."""
    image = (
        await db.execute(
            select(QuoteHandoffImage)
            .options(load_only(QuoteHandoffImage.id))
            .where(
                QuoteHandoffImage.id == image_id,
                QuoteHandoffImage.workspace_id == _quote.workspace_id,
                QuoteHandoffImage.quote_id == _quote.id,
            )
        )
    ).scalar_one_or_none()
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Handoff image not found",
        )
    await db.delete(image)
    await db.commit()
    logger.info(
        "quote_handoff_image_deleted",
        workspace_id=str(_quote.workspace_id),
        quote_id=str(_quote.id),
        image_id=str(image_id),
    )


@router.put("/{quote_id}", response_model=QuoteDetailResponse)
async def update_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    quote_in: QuoteUpdate,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Update a quote's header fields (totals are re-derived)."""
    service = QuoteService(db)
    return await service.update_quote(workspace_id, quote_id, quote_in)


@router.put("/{quote_id}/assignment", response_model=QuoteDetailResponse)
async def assign_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: QuoteAssignmentRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
    _quote: ScopedQuote,
) -> QuoteDetailResponse:
    """Reassign or clear a quote's sales owner in any lifecycle state."""
    service = QuoteService(db)
    return await service.assign_quote(workspace_id, quote_id, payload.assigned_user_id)


@router.delete("/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> None:
    """Delete a draft/sent quote. Decided or expired quotes are kept."""
    service = QuoteService(db)
    await service.delete_quote(workspace_id, quote_id)


# Lifecycle transitions
@router.post("/{quote_id}/send", response_model=QuoteDetailResponse)
async def send_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Mark a quote as sent and email it to the quote-to contact."""
    service = QuoteService(db)
    return await service.mark_sent(workspace_id, quote_id)


@router.post("/{quote_id}/deliver", response_model=QuoteDeliverResult)
async def deliver_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: QuoteDeliverRequest,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
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
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Operator approves a quote on the customer's behalf."""
    service = QuoteService(db)
    return await service.approve_quote(workspace_id, quote_id)


@router.post("/{quote_id}/decline", response_model=QuoteDetailResponse)
async def decline_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: QuoteDeclineRequest,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Operator declines a quote on the customer's behalf."""
    service = QuoteService(db)
    return await service.decline_quote(workspace_id, quote_id, reason=payload.reason)


@router.post("/{quote_id}/reopen", response_model=QuoteDetailResponse)
async def reopen_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Put a lapsed quote back in front of the customer on a fresh window."""
    service = QuoteService(db)
    return await service.reopen_quote(workspace_id, quote_id)


@router.post("/{quote_id}/record-deposit", response_model=QuoteDetailResponse)
async def record_quote_deposit(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: QuoteDepositRecordRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
    _quote: ScopedQuote,
) -> QuoteDetailResponse:
    """Attest that an offline cash, check, or other deposit was received."""
    owner_user_id = quote_owner_scope(membership.role, current_user.id)
    await record_manual_deposit(
        db,
        workspace_id,
        quote_id,
        payment_method=payload.payment_method,
        recorded_by_id=current_user.id,
        owner_user_id=owner_user_id,
    )
    return await QuoteService(db).get_quote(workspace_id, quote_id)


@router.post("/{quote_id}/convert", response_model=QuoteConvertResponse)
async def convert_quote(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: QuoteConvertRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
    _quote: ScopedQuote,
) -> QuoteConvertResponse:
    """Convert an approved quote into a scheduled job and/or an invoice."""
    can_create_invoice = role_can(membership.role, Capability.BILLING_WRITE)
    if payload.create_invoice and not can_create_invoice and _quote.converted_invoice_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Billing access is required to create an invoice.",
        )

    service = QuoteService(db)
    result = await service.convert_quote(
        workspace_id,
        quote_id,
        create_job=payload.create_job,
        create_invoice=payload.create_invoice,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_end,
        crew_id=payload.crew_id,
        technician_ids=payload.technician_ids,
        confirm_unpaid_deposit=payload.confirm_unpaid_deposit,
        allow_invoice_creation=can_create_invoice,
        owner_user_id=quote_owner_scope(membership.role, current_user.id),
    )
    if result.job_id is None or payload.scheduled_start is None:
        return result

    recipients = await JobService(db).assignment_recipient_user_ids(result.job_id, workspace_id)
    if not recipients:
        result.crew_notification = CrewNotificationResult(status="not_applicable")
        return result

    assert payload.scheduled_start is not None
    assert payload.scheduled_end is not None
    schedule_version = (
        f"{payload.scheduled_start.isoformat()}:{payload.scheduled_end.isoformat()}:"
        f"{payload.crew_id}:{','.join(sorted(map(str, payload.technician_ids)))}"
    )
    dedupe_key = f"job_assignment:{result.job_id}:{schedule_version}"
    recipient_keys = {user_id: f"{dedupe_key}:recipient:{user_id}" for user_id in recipients}
    pending_recipient_list: list[int] = []
    for user_id in recipients:
        already_delivered = await redis_idempotency_key_exists(
            recipient_keys[user_id],
            log=logger,
            failure_event="job_assignment_dedupe_unavailable",
        )
        if not already_delivered:
            pending_recipient_list.append(user_id)
    pending_recipients = tuple(pending_recipient_list)
    if not pending_recipients:
        result.crew_notification = CrewNotificationResult(
            status="sent",
            recipient_count=len(recipients),
            sent_count=len(recipients),
        )
        return result
    try:
        delivery = await notify_workspace_event(
            db,
            workspace_id=workspace_id,
            notification_type="job_assignment",
            title="Landscape installation assigned",
            body="Your installation plan is available in Tribunal.",
            data={
                "type": "job_assignment",
                "jobId": str(result.job_id),
                "screen": f"/(tabs)/jobs/{result.job_id}",
            },
            channel_id="jobs",
            email_subject="Landscape installation assigned",
            email_heading="Installation assignment",
            email_intro="Your installation plan is available in Tribunal.",
            email_details={
                "Scheduled": payload.scheduled_start.astimezone(UTC).strftime(
                    "%b %d, %Y at %I:%M %p UTC"
                ),
                "Job": str(result.job_id),
            },
            dedupe_key=dedupe_key,
            recipient_user_ids=pending_recipients,
        )
        for user_id in delivery.delivered_recipient_ids:
            await set_redis_idempotency_key(
                recipient_keys[user_id],
                ttl_seconds=60 * 60 * 24 * 30,
                log=logger,
                failure_event="job_assignment_dedupe_unavailable",
            )
        already_sent = len(recipients) - len(pending_recipients)
        sent = already_sent + delivery.delivered_recipient_count
        failed = delivery.failed_recipient_count
        notification_status: Literal["sent", "partial", "failed"] = (
            "sent" if sent == len(recipients) else "partial" if sent > 0 else "failed"
        )
        result.crew_notification = CrewNotificationResult(
            status=notification_status,
            recipient_count=len(recipients),
            sent_count=sent,
            failed_count=failed,
        )
    except Exception:  # Delivery is post-commit and must not lie about conversion.
        result.crew_notification = CrewNotificationResult(
            status="failed",
            recipient_count=len(recipients),
            failed_count=len(pending_recipients),
        )
    return result


# Sales wizard: config-driven multi-tier proposal builder. Preview computes the
# document without persisting; save materializes a draft quote (server-recomputed
# headline-tier line items) plus the rich snapshot on ``proposal_document``.
@router.post("/wizard/preview", response_model=ProposalDocument)
async def preview_wizard_proposal(
    workspace_id: uuid.UUID,
    payload: ProposalWizardPayload,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadQuotes,
) -> ProposalDocument:
    """Compute the full multi-tier proposal document without saving."""
    service = QuoteService(db)
    try:
        return await service.preview_from_wizard(workspace_id, payload)
    except BistroPricingConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/wizard/inventory-availability",
    response_model=QuoteInventoryAvailabilityResponse,
)
async def preview_wizard_inventory_availability(
    workspace_id: uuid.UUID,
    payload: ProposalWizardPayload,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadQuotes,
) -> QuoteInventoryAvailabilityResponse:
    """Check private fulfillment requirements against available-to-promise stock."""
    try:
        document = await QuoteService(db).preview_from_wizard(workspace_id, payload)
    except BistroPricingConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await QuoteInventoryAvailabilityService(db).check(workspace_id, document.fulfillment)


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
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Save a wizard proposal as a draft quote + its multi-tier snapshot."""
    service = QuoteService(db)
    try:
        return await service.save_from_wizard(
            workspace_id,
            payload,
            created_by_id=current_user.id,
            assigned_user_id=quote_owner_scope(membership.role, current_user.id),
        )
    except BistroPricingConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put("/{quote_id}/wizard", response_model=QuoteDetailResponse)
async def update_wizard_proposal(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: ProposalWizardPayload,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Reprice an unpaid draft/sent wizard quote without replacing its link."""
    try:
        return await QuoteService(db).update_from_wizard(workspace_id, quote_id, payload)
    except BistroPricingConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/{quote_id}/revisions",
    response_model=QuoteDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def revise_wizard_proposal(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: ProposalWizardPayload,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Create a separately numbered draft from a protected wizard quote."""
    try:
        return await QuoteService(db).revise_from_wizard(
            workspace_id, quote_id, payload, created_by_id=current_user.id
        )
    except BistroPricingConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# Roofline estimator: price permanent vs seasonal for a measured linear-feet
# figure. Feet is the only client input; every dollar is server-computed.
@router.post("/estimate", response_model=LinearFeetEstimateResult)
async def estimate_linear_feet(
    workspace_id: uuid.UUID,
    payload: LinearFeetEstimateRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadQuotes,
) -> LinearFeetEstimateResult:
    """Compute a permanent-vs-temporary estimate for a measured roofline."""
    service = QuoteService(db)
    return await service.estimate_linear_feet(workspace_id, payload)


@router.post("/estimate/render", response_model=EstimateRenderResult)
async def render_estimate(
    workspace_id: uuid.UUID,
    payload: EstimateRenderRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> EstimateRenderResult:
    """Turn a drawn lighting design into a photorealistic night render.

    Server-side OpenAI image edit using the workspace credential — no browser
    key. Spends per image, hence ``billing:write``.
    """
    service = QuoteService(db)
    return await service.render_estimate(workspace_id, payload, requested_by_id=current_user.id)


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
    membership: CanWriteQuotes,
) -> ComparisonShareResult:
    """Persist a comparison behind a token and return the client-facing link."""
    service = QuoteService(db)
    return await service.share_comparison(workspace_id, payload, created_by_id=current_user.id)


@router.post(
    "/estimate/quote",
    response_model=QuoteDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def convert_estimate_to_quote(
    workspace_id: uuid.UUID,
    payload: EstimateQuoteRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Create a draft quote from a measured roofline estimate.

    Prices the chosen permanent or seasonal side server-side and turns each
    grossed component into a quote line — the estimator's core "design → quote"
    step. Returns the created draft quote.
    """
    service = QuoteService(db)
    return await service.create_quote_from_estimate(
        workspace_id,
        payload,
        created_by_id=current_user.id,
        assigned_user_id=quote_owner_scope(membership.role, current_user.id),
    )


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
    """Send a saved estimate's client link to the customer by email or SMS."""
    service = QuoteService(db)
    return await service.deliver_comparison(
        workspace_id, token, channel=payload.channel, to=payload.to
    )


# Service sub-resource: "add gutters to that quote we already sent".
#
# Deliberately separate from the line-item endpoints below, which write straight
# to ``quote_line_items``. That is the correct persistence only for a plain
# quote. On a quote built by the sales wizard the line items are *derived* from
# ``proposal_document`` and get rebuilt from it whenever the quote reprices, so a
# line item written directly here would never reach the client proposal (which
# renders the document) and would be deleted outright the next time the client
# picked a different package. These endpoints take the operator's intent and let
# the service pick the persistence that actually survives on that quote.
@router.post(
    "/{quote_id}/services",
    response_model=QuoteDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_service(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: QuoteServiceCreate,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Add a service to an existing quote and reprice it."""
    service = QuoteService(db)
    return await service.add_service(workspace_id, quote_id, payload)


@router.delete("/{quote_id}/services/{service_id}", response_model=QuoteDetailResponse)
async def remove_service(
    workspace_id: uuid.UUID,
    quote_id: uuid.UUID,
    service_id: str,
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
) -> QuoteDetailResponse:
    """Remove a service previously added to a quote and reprice it."""
    service = QuoteService(db)
    return await service.remove_service(workspace_id, quote_id, service_id)


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
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
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
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
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
    _quote: ScopedQuote,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteQuotes,
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
async def approve_public_proposal(
    token: str,
    db: DB,
    payload: PublicProposalApprove,
) -> PublicProposalActionResult:
    """Client approves their proposal (idempotent; expired/declined rejected).

    An optional ``selected_tier`` names the package they chose; the server
    re-derives that package's lines, totals, and deposit from the saved snapshot
    before approving. The rendered proposal version is required to prevent accepting stale terms.
    """
    return await QuoteService(db).approve_public(
        token,
        proposal_version=payload.proposal_version,
        selected_tier=payload.selected_tier,
    )


@public_router.post("/{token}/decline", response_model=PublicProposalActionResult)
async def decline_public_proposal(
    token: str,
    payload: PublicProposalDecline,
    db: DB,
) -> PublicProposalActionResult:
    """Client declines their proposal with an optional reason (idempotent)."""
    return await QuoteService(db).decline_public(token, reason=payload.reason)


@public_router.post("/{token}/view", status_code=status.HTTP_204_NO_CONTENT)
async def record_public_proposal_view(token: str, db: DB) -> None:
    """Record that the client opened their proposal (fire-and-forget beacon).

    Deliberately a POST rather than a write inside the GET: the read stays pure
    and cacheable, every retry/refetch does not amplify into a write on an
    unauthenticated path, and there is exactly one narrow, throttled write
    surface. Repeat beacons inside the service's throttle window are a no-op,
    and an unknown token 404s before anything is written.
    """
    await QuoteService(db).record_public_view(token)


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


@comparison_public_router.post("/{token}/decline", response_model=PublicComparisonDeclineResult)
async def decline_public_comparison(
    token: str,
    payload: PublicComparisonDecline,
    db: DB,
) -> PublicComparisonDeclineResult:
    """Client declines a shared estimate, with an optional reason (idempotent).

    Without this the estimate link is a dead end: the client can read a price but
    has no way to say no, so the rep keeps chasing a decision that was already
    made. Repeat calls keep the first decline's timestamp. Unknown tokens 404.
    """
    return await QuoteService(db).decline_public_comparison(token, reason=payload.reason)
