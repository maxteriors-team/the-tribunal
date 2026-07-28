"""Self-serve onboarding endpoints.

Every route here acts on the caller's *active* workspace (their default
membership) rather than an explicit ``workspace_id``, and the actions are
privileged: creating the reactivation agent, overwriting the workspace's Cal.com
credential, and purchasing a Telnyx number on the owner's account. They are
therefore gated on ``workspace:manage`` (owner/admin tier) via
:data:`~app.api.deps.CanManageActiveWorkspace`, which authorizes the caller's
role **in the resolved workspace**. Authentication alone is not enough: any
member may point their default at another workspace they belong to with
``POST /workspaces/{workspace_id}/set-default``.

The gate is a dependency over the current user + DB session only, so it adds no
parameters to these routes and leaves the published OpenAPI contract unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile, status

from app.api.deps import DB, CanManageActiveWorkspace, CurrentUser
from app.schemas.onboarding import (
    LaunchCampaignResponse,
    OnboardRequest,
    OnboardResponse,
    ParseCalcomUrlRequest,
    ParseCalcomUrlResponse,
    VerifyCalcomResponse,
)
from app.services.onboarding.credentials import get_workspace_calcom_api_key
from app.services.onboarding.exceptions import OnboardingServiceError
from app.services.onboarding.external_checks import (
    resolve_calcom_event_type_id,
    verify_calcom_api_key,
)
from app.services.onboarding.route_responses import (
    launch_campaign_response,
    onboard_response,
    parse_calcom_url_response,
    raise_onboarding_http_error,
    verify_calcom_response,
)
from app.services.onboarding.workspace_setup import (
    CampaignInput,
    OnboardingInput,
    complete_onboarding,
    get_managed_user_workspace,
    launch_campaign_from_csv,
)

router = APIRouter()


@router.post(
    "/onboard",
    response_model=OnboardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def onboard(
    request: OnboardRequest,
    current_user: CurrentUser,
    db: DB,
    _gate: CanManageActiveWorkspace,
) -> OnboardResponse:
    """Complete onboarding in a single call."""
    try:
        result = await complete_onboarding(
            db=db,
            current_user_id=current_user.id,
            request=OnboardingInput(
                calcom_api_key=request.calcom_api_key,
                calcom_event_type_id=request.calcom_event_type_id,
                area_code=request.area_code,
            ),
        )
    except OnboardingServiceError as exc:
        raise_onboarding_http_error(exc)
    return onboard_response(result)


@router.post(
    "/campaigns",
    response_model=LaunchCampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign(
    current_user: CurrentUser,
    db: DB,
    _gate: CanManageActiveWorkspace,
    file: UploadFile,
    skip_duplicates: bool = Form(default=True),
    campaign_name: str | None = Form(default=None),
) -> LaunchCampaignResponse:
    """Upload a CSV and launch a lead-reactivation campaign."""
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
        result = await launch_campaign_from_csv(
            db=db,
            current_user_id=current_user.id,
            request=CampaignInput(
                file_content=content,
                skip_duplicates=skip_duplicates,
                campaign_name=campaign_name,
            ),
        )
    except OnboardingServiceError as exc:
        raise_onboarding_http_error(exc)
    return launch_campaign_response(result)


@router.post("/parse-calcom-url", response_model=ParseCalcomUrlResponse)
async def parse_calcom_url(
    request: ParseCalcomUrlRequest,
    current_user: CurrentUser,
    db: DB,
    _gate: CanManageActiveWorkspace,
) -> ParseCalcomUrlResponse:
    """Parse a Cal.com booking URL and resolve the event_type_id."""
    try:
        workspace = await get_managed_user_workspace(current_user.id, db)
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
    _gate: CanManageActiveWorkspace,
    api_key: str = Query(..., min_length=1, description="Cal.com API key to verify"),
) -> VerifyCalcomResponse:
    """Verify a Cal.com API key by calling the /me endpoint."""
    try:
        result = await verify_calcom_api_key(api_key)
    except OnboardingServiceError as exc:
        raise_onboarding_http_error(exc)
    return verify_calcom_response(result)
