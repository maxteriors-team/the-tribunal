"""Realtor self-serve onboarding endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, get_workspace
from app.db.scope import apply_workspace_scope
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.workspace import Workspace
from app.schemas.realtor import (
    ParseCalcomUrlRequest,
    ParseCalcomUrlResponse,
    RealtorCampaignResponse,
    RealtorOnboardRequest,
    RealtorOnboardResponse,
    VerifyCalcomResponse,
)
from app.services.onboarding.credentials import get_workspace_calcom_api_key
from app.services.onboarding.exceptions import OnboardingServiceError
from app.services.onboarding.external_checks import (
    resolve_calcom_event_type_id,
    verify_calcom_api_key,
)
from app.services.onboarding.route_responses import (
    parse_calcom_url_response,
    raise_onboarding_http_error,
    realtor_campaign_response,
    realtor_onboard_response,
    verify_calcom_response,
)
from app.services.onboarding.workspace_setup import (
    RealtorCampaignInput,
    RealtorOnboardingInput,
    complete_realtor_onboarding,
    get_user_workspace,
    launch_realtor_campaign_from_csv,
)

router = APIRouter()
workspace_router = APIRouter()


class RealtorStatsResponse(BaseModel):
    """Realtor dashboard stats."""

    leads_uploaded: int
    texts_sent: int
    replies_received: int
    appointments_booked: int


@workspace_router.get("/stats", response_model=RealtorStatsResponse)
async def get_realtor_stats(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> RealtorStatsResponse:
    """Get realtor dashboard statistics for a workspace."""
    leads_result = await db.execute(
        apply_workspace_scope(
            select(func.count()).select_from(Contact),
            Contact,
            workspace_id,
        )
    )
    leads_uploaded = leads_result.scalar() or 0

    workspace_conversations = apply_workspace_scope(
        select(Conversation.id), Conversation, workspace_id
    )

    texts_sent_result = await db.execute(
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id.in_(workspace_conversations),
            Message.direction == MessageDirection.OUTBOUND,
        )
    )
    texts_sent = texts_sent_result.scalar() or 0

    replies_result = await db.execute(
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id.in_(workspace_conversations),
            Message.direction == MessageDirection.INBOUND,
        )
    )
    replies_received = replies_result.scalar() or 0

    appointments_result = await db.execute(
        apply_workspace_scope(
            select(func.count()).select_from(Appointment),
            Appointment,
            workspace_id,
        ).where(
            Appointment.status.in_(
                [
                    AppointmentStatus.SCHEDULED,
                    AppointmentStatus.COMPLETED,
                ]
            ),
        )
    )
    appointments_booked = appointments_result.scalar() or 0

    return RealtorStatsResponse(
        leads_uploaded=leads_uploaded,
        texts_sent=texts_sent,
        replies_received=replies_received,
        appointments_booked=appointments_booked,
    )


@router.post(
    "/onboard",
    response_model=RealtorOnboardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def realtor_onboard(
    request: RealtorOnboardRequest,
    current_user: CurrentUser,
    db: DB,
) -> RealtorOnboardResponse:
    """Complete realtor onboarding in a single call."""
    try:
        result = await complete_realtor_onboarding(
            db=db,
            current_user_id=current_user.id,
            request=RealtorOnboardingInput(
                calcom_api_key=request.calcom_api_key,
                calcom_event_type_id=request.calcom_event_type_id,
                area_code=request.area_code,
                fub_api_key=request.fub_api_key,
            ),
        )
    except OnboardingServiceError as exc:
        raise_onboarding_http_error(exc)
    return realtor_onboard_response(result)


@router.post(
    "/campaigns",
    response_model=RealtorCampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_realtor_campaign(
    current_user: CurrentUser,
    db: DB,
    file: UploadFile,
    skip_duplicates: bool = Form(default=True),
    campaign_name: str | None = Form(default=None),
) -> RealtorCampaignResponse:
    """Upload a CSV and launch a realtor lead-reactivation campaign."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV file.",
        )

    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {exc!s}",
        ) from exc

    try:
        result = await launch_realtor_campaign_from_csv(
            db=db,
            current_user_id=current_user.id,
            request=RealtorCampaignInput(
                file_content=content,
                skip_duplicates=skip_duplicates,
                campaign_name=campaign_name,
            ),
        )
    except OnboardingServiceError as exc:
        raise_onboarding_http_error(exc)
    return realtor_campaign_response(result)


@router.post("/parse-calcom-url", response_model=ParseCalcomUrlResponse)
async def parse_calcom_url(
    request: ParseCalcomUrlRequest,
    current_user: CurrentUser,
    db: DB,
) -> ParseCalcomUrlResponse:
    """Parse a Cal.com booking URL and resolve the event_type_id."""
    try:
        workspace = await get_user_workspace(current_user.id, db)
        api_key = await get_workspace_calcom_api_key(workspace.id, db)
        if api_key is None:
            api_key = request.api_key
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "No Cal.com API key found for this workspace. "
                    "Provide one via the api_key field or connect Cal.com in Settings first."
                ),
            )
        result = await resolve_calcom_event_type_id(url=request.url, api_key=api_key)
    except OnboardingServiceError as exc:
        raise_onboarding_http_error(exc)
    return parse_calcom_url_response(result)


@router.get("/verify-calcom", response_model=VerifyCalcomResponse)
async def verify_calcom(
    current_user: CurrentUser,
    api_key: str = Query(..., min_length=1, description="Cal.com API key to verify"),
) -> VerifyCalcomResponse:
    """Verify a Cal.com API key by calling the /me endpoint."""
    try:
        result = await verify_calcom_api_key(api_key)
    except OnboardingServiceError as exc:
        raise_onboarding_http_error(exc)
    return verify_calcom_response(result)
