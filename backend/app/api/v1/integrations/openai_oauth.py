"""OpenAI Codex OAuth integration endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.api.deps import (
    DB,
    CurrentUser,
    WorkspaceAccess,
    WorkspaceAdminAccess,
    require_route_capabilities,
)
from app.core.permissions import Capability
from app.services.ai.openai_oauth import (
    OpenAIOAuthError,
    build_openai_oauth_start,
    complete_openai_oauth_callback,
    disconnect_openai_oauth,
    get_openai_oauth_status,
    poll_openai_oauth_device_code,
)

router = APIRouter(
    dependencies=[
        Depends(
            require_route_capabilities(Capability.WORKSPACE_MANAGE, Capability.WORKSPACE_MANAGE)
        )
    ]
)
public_router = APIRouter()


class OpenAIOAuthStartResponse(BaseModel):
    """OpenAI subscription sign-in instructions."""

    method: str
    expires_at: int
    authorization_url: str | None = None
    redirect_uri: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    poll_token: str | None = None
    poll_interval_seconds: int = 5


class OpenAIOAuthStatusResponse(BaseModel):
    """Safe OpenAI subscription login status."""

    connected: bool
    account_id: str | None = None
    email: str | None = None
    expires_at: int | None = None
    saved_at: str | None = None
    auth_method: str | None = None
    plan_type: str | None = None
    api_key_configured: bool = False
    realtime_model: str


class OpenAIOAuthDevicePollRequest(BaseModel):
    """Encrypted device-code polling token from the start response."""

    poll_token: str


class OpenAIOAuthDevicePollResponse(BaseModel):
    """One device-code polling result."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    pending: bool
    status: OpenAIOAuthStatusResponse


@router.get("/openai/oauth/status", response_model=OpenAIOAuthStatusResponse)
async def get_openai_subscription_status(
    workspace: WorkspaceAccess,
    db: DB,
) -> OpenAIOAuthStatusResponse:
    """Return the workspace's ChatGPT subscription sign-in status."""
    status_snapshot = await get_openai_oauth_status(db, workspace.id)
    return OpenAIOAuthStatusResponse(**asdict(status_snapshot))


@router.post("/openai/oauth/start", response_model=OpenAIOAuthStartResponse)
async def start_openai_subscription_login(
    workspace: WorkspaceAdminAccess,
    current_user: CurrentUser,
) -> OpenAIOAuthStartResponse:
    """Create Codex browser or device-code instructions for ChatGPT subscription auth."""
    try:
        start = await build_openai_oauth_start(workspace.id, current_user.id)
    except OpenAIOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return OpenAIOAuthStartResponse(**asdict(start))


@router.post("/openai/oauth/device/poll", response_model=OpenAIOAuthDevicePollResponse)
async def poll_openai_subscription_device_login(
    workspace: WorkspaceAdminAccess,
    current_user: CurrentUser,
    request: OpenAIOAuthDevicePollRequest,
) -> OpenAIOAuthDevicePollResponse:
    """Poll OpenAI device-code sign-in once and persist credentials when complete."""
    try:
        result = await poll_openai_oauth_device_code(
            request.poll_token,
            workspace_id=workspace.id,
            user_id=current_user.id,
        )
    except OpenAIOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return OpenAIOAuthDevicePollResponse(
        pending=result.pending,
        status=OpenAIOAuthStatusResponse(**asdict(result.status)),
    )


@router.delete("/openai/oauth", response_model=OpenAIOAuthStatusResponse)
async def disconnect_openai_subscription_login(
    workspace: WorkspaceAdminAccess,
    db: DB,
) -> OpenAIOAuthStatusResponse:
    """Disconnect ChatGPT subscription credentials for the workspace."""
    status_snapshot = await disconnect_openai_oauth(db, workspace.id)
    return OpenAIOAuthStatusResponse(**asdict(status_snapshot))


@public_router.get("/callback")
async def complete_openai_subscription_login(
    code: str = Query(...),
    state: str = Query(...),
) -> dict[str, str]:
    """Hosted OAuth callback for custom OpenAI OAuth clients/redirect URIs."""
    try:
        await complete_openai_oauth_callback(code=code, state=state)
    except OpenAIOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {"status": "connected"}
