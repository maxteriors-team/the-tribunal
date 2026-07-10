"""Google Calendar OAuth integration endpoints (per-workspace connect flow)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.deps import DB, CurrentUser, WorkspaceAccess, WorkspaceAdminAccess
from app.core.config import settings
from app.services.calendar.google.oauth import (
    GoogleOAuthError,
    build_google_oauth_start,
    complete_google_oauth_callback,
    disconnect_google_calendar,
    get_google_calendar_status,
)

router = APIRouter()
public_router = APIRouter()


class GoogleCalendarConnectResponse(BaseModel):
    """Consent-screen redirect instructions for the browser."""

    authorization_url: str
    redirect_uri: str
    expires_at: int


class GoogleCalendarStatusResponse(BaseModel):
    """Safe Google Calendar connection status."""

    connected: bool
    google_calendar_id: str | None = None
    token_expiry: str | None = None
    scopes: str | None = None
    saved_at: str | None = None
    client_configured: bool = False


@router.post("/google-calendar/connect", response_model=GoogleCalendarConnectResponse)
async def connect_google_calendar(
    workspace: WorkspaceAdminAccess,
    current_user: CurrentUser,
) -> GoogleCalendarConnectResponse:
    """Return a Google consent URL for the workspace admin to connect a calendar."""
    try:
        start = build_google_oauth_start(workspace.id, current_user.id)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return GoogleCalendarConnectResponse(**asdict(start))


@router.get("/google-calendar/status", response_model=GoogleCalendarStatusResponse)
async def google_calendar_status(
    workspace: WorkspaceAccess,
    db: DB,
) -> GoogleCalendarStatusResponse:
    """Return the workspace's Google Calendar connection status."""
    snapshot = await get_google_calendar_status(db, workspace.id)
    return GoogleCalendarStatusResponse(**asdict(snapshot))


@router.delete("/google-calendar", response_model=GoogleCalendarStatusResponse)
async def disconnect_google_calendar_endpoint(
    workspace: WorkspaceAdminAccess,
    db: DB,
) -> GoogleCalendarStatusResponse:
    """Disconnect (deactivate + revoke) the workspace's Google Calendar."""
    snapshot = await disconnect_google_calendar(db, workspace.id)
    return GoogleCalendarStatusResponse(**asdict(snapshot))


@public_router.get("/callback")
async def google_calendar_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Hosted OAuth callback: exchange the code, persist tokens, bounce to the UI."""
    redirect_base = f"{settings.frontend_url.rstrip('/')}/settings"
    if error or not code or not state:
        return RedirectResponse(url=f"{redirect_base}?google_calendar=error")
    try:
        await complete_google_oauth_callback(code=code, state=state)
    except GoogleOAuthError:
        return RedirectResponse(url=f"{redirect_base}?google_calendar=error")
    return RedirectResponse(url=f"{redirect_base}?google_calendar=connected")
