"""Reviews & Reputation engine endpoints.

Authenticated, workspace-scoped routes power the operator dashboard and
settings; the public router powers the no-auth rating landing page that
implements the negative-feedback firewall (the rating gate).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DB, CanManageWorkspace, CurrentUser, get_workspace, require_capability
from app.core.permissions import Capability
from app.models.workspace import Workspace
from app.schemas.review import (
    GeneratedReviewReply,
    PaginatedReviewRequests,
    PaginatedReviews,
    PublicFeedbackResult,
    PublicFeedbackSubmit,
    PublicRatingResult,
    PublicRatingSubmit,
    PublicReviewRequest,
    ReputationSummary,
    ReviewCreate,
    ReviewReplyGenerateRequest,
    ReviewRequestCreate,
    ReviewRequestSendResult,
    ReviewResponse,
    ReviewSettings,
    ReviewSettingsUpdate,
    ReviewUpdate,
)
from app.services.ai.review_reply_generator import generate_review_reply
from app.services.reviews import ReviewService

# Reputation data is customer data (names, ratings, private feedback), so
# ``crm:read`` is the floor for the whole authenticated router — the same gate
# ``/contacts`` uses. The public rating-gate router below is deliberately
# unauthenticated and carries no dependency.
router = APIRouter(dependencies=[Depends(require_capability(Capability.CRM_READ))])
public_router = APIRouter()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=ReviewSettings)
async def get_review_settings(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    _gate: CanManageWorkspace,
) -> ReviewSettings:
    """Get reputation engine settings for the workspace."""
    return ReviewService(db).get_settings(workspace)


@router.put("/settings", response_model=ReviewSettings)
async def update_review_settings(
    workspace_id: uuid.UUID,
    update: ReviewSettingsUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    _gate: CanManageWorkspace,
) -> ReviewSettings:
    """Update reputation engine settings for the workspace."""
    return await ReviewService(db).update_settings(workspace, update.model_dump(exclude_unset=True))


# ---------------------------------------------------------------------------
# Reputation dashboard
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=ReputationSummary)
async def get_reputation_summary(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ReputationSummary:
    """Aggregate reputation metrics for the workspace dashboard."""
    return await ReviewService(db).get_summary(workspace_id)


# ---------------------------------------------------------------------------
# Review requests
# ---------------------------------------------------------------------------


@router.get("/requests", response_model=PaginatedReviewRequests)
async def list_review_requests(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
) -> PaginatedReviewRequests:
    """List review requests for the workspace."""
    return await ReviewService(db).list_requests(
        workspace_id, page=page, page_size=page_size, status_filter=status_filter
    )


@router.post(
    "/requests",
    response_model=ReviewRequestSendResult,
    status_code=status.HTTP_201_CREATED,
    # Texts a customer from a workspace number, so it needs the same capability
    # as any other outbound message rather than just the router's read floor.
    # Finding 2 of docs/technician-role-audit.md.
    dependencies=[Depends(require_capability(Capability.COMMS_SEND))],
)
async def create_review_request(
    workspace_id: uuid.UUID,
    request_in: ReviewRequestCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ReviewRequestSendResult:
    """Create and optionally dispatch a review-request SMS to a contact."""
    return await ReviewService(db).create_request(
        workspace,
        contact_id=request_in.contact_id,
        appointment_id=request_in.appointment_id,
        send_now=request_in.send_now,
    )


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedReviews)
async def list_reviews(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    is_public: bool | None = Query(None),
    sentiment: str | None = Query(None),
) -> PaginatedReviews:
    """List collected reviews and private feedback for the workspace."""
    return await ReviewService(db).list_reviews(
        workspace_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        is_public=is_public,
        sentiment=sentiment,
    )


@router.post("", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    workspace_id: uuid.UUID,
    review_in: ReviewCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ReviewResponse:
    """Manually create a review (operator entry)."""
    review = await ReviewService(db).create_review(
        workspace_id,
        rating=review_in.rating,
        body=review_in.body,
        reviewer_name=review_in.reviewer_name,
        contact_id=review_in.contact_id,
        source=review_in.source.value,
        is_public=review_in.is_public,
    )
    return ReviewService._review_to_response(review)


@router.get("/{review_id}", response_model=ReviewResponse)
async def get_review(
    workspace_id: uuid.UUID,
    review_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ReviewResponse:
    """Get a single review."""
    review = await ReviewService(db).get_review(workspace_id, review_id)
    return ReviewService._review_to_response(review)


@router.put("/{review_id}", response_model=ReviewResponse)
async def update_review(
    workspace_id: uuid.UUID,
    review_id: uuid.UUID,
    review_in: ReviewUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ReviewResponse:
    """Update a review's triage state or reply draft."""
    update_data = review_in.model_dump(exclude_unset=True)
    review = await ReviewService(db).update_review(workspace_id, review_id, update_data)
    return ReviewService._review_to_response(review)


@router.post("/{review_id}/generate-reply", response_model=GeneratedReviewReply)
async def generate_reply(
    workspace_id: uuid.UUID,
    review_id: uuid.UUID,
    request: ReviewReplyGenerateRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> GeneratedReviewReply:
    """Draft an on-brand AI reply for a review.

    The draft is persisted on the review so operators can edit before sending.
    """
    service = ReviewService(db)
    review = await service.get_review(workspace_id, review_id)
    review_settings = service.get_settings(workspace)

    result = await generate_review_reply(
        rating=review.rating,
        review_body=review.body,
        is_public=review.is_public,
        business_name=review_settings.business_name,
        reviewer_name=review.reviewer_name,
        tone=request.tone or review_settings.reply_tone,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("error", "Failed to generate reply"),
        )

    await service.update_review(workspace_id, review_id, {"reply_draft": result["reply"]})
    return GeneratedReviewReply(**result)


# ---------------------------------------------------------------------------
# Public rating gate (no auth)
# ---------------------------------------------------------------------------


@public_router.get("/{token}", response_model=PublicReviewRequest)
async def get_public_review_request(
    token: str,
    db: DB,
) -> PublicReviewRequest:
    """Public landing-page data for a review-request token."""
    return await ReviewService(db).get_public_request(token)


@public_router.post("/{token}/rate", response_model=PublicRatingResult)
async def submit_public_rating(
    token: str,
    submission: PublicRatingSubmit,
    db: DB,
) -> PublicRatingResult:
    """Submit a star rating; applies the rating gate routing."""
    return await ReviewService(db).submit_rating(token, submission.rating)


@public_router.post("/{token}/feedback", response_model=PublicFeedbackResult)
async def submit_public_feedback(
    token: str,
    submission: PublicFeedbackSubmit,
    db: DB,
) -> PublicFeedbackResult:
    """Submit private feedback for a low rating (firewall path)."""
    await ReviewService(db).submit_feedback(token, submission.body, submission.reviewer_name)
    return PublicFeedbackResult(
        success=True,
        message="Thank you for your feedback. We'll be in touch.",
    )
