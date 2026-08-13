"""Per-user Google Calendar OAuth endpoints."""

from __future__ import annotations

from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.schemas.google_calendar import (
    GoogleCalendarAuthorizeRequest,
    GoogleCalendarAuthorizeResponse,
    GoogleCalendarStatus,
)
from app.services import google_calendar as google_calendar_service
from app.services.google_calendar import GoogleCalendarError

router = APIRouter(prefix="/integrations/google-calendar", tags=["Google Calendar"])
logger = structlog.get_logger(__name__)


def _redirect_result(
    return_url: str, *, result: str, detail: str | None = None
) -> RedirectResponse:
    separator = "&" if "?" in return_url else "?"
    query: dict[str, str] = {"google_calendar": result}
    if detail:
        query["detail"] = detail
    return RedirectResponse(f"{return_url}{separator}{urlencode(query)}", status_code=303)


@router.get("/status", response_model=GoogleCalendarStatus)
async def connection_status(db: DB, current_user: CurrentUser) -> GoogleCalendarStatus:
    connection = await google_calendar_service.get_connection(db, current_user.id)
    return GoogleCalendarStatus(
        configured=google_calendar_service.google_calendar_configured(),
        connected=connection is not None,
        google_email=connection.google_email if connection else None,
        calendar_id=connection.calendar_id if connection else None,
        connected_at=connection.created_at if connection else None,
    )


@router.post("/authorize", response_model=GoogleCalendarAuthorizeResponse)
async def authorize(
    payload: GoogleCalendarAuthorizeRequest,
    current_user: CurrentUser,
) -> GoogleCalendarAuthorizeResponse:
    url = await google_calendar_service.create_authorization_url(
        user_id=current_user.id,
        return_url=payload.return_url,
    )
    return GoogleCalendarAuthorizeResponse(authorization_url=url)


@router.get("/callback", include_in_schema=False)
async def callback(
    db: DB,
    state: str = Query(min_length=20, max_length=512),
    code: str | None = Query(default=None, max_length=4096),
    error: str | None = Query(default=None, max_length=200),
) -> RedirectResponse:
    """Finish Google OAuth without relying on the app's login cookie."""
    try:
        oauth_state = await google_calendar_service.consume_oauth_state(state)
    except GoogleCalendarError:
        fallback = f"{settings.frontend_url.rstrip('/')}/settings?tab=calendar"
        return _redirect_result(fallback, result="error", detail="Authorization expired")

    if error or not code:
        return _redirect_result(oauth_state.return_url, result="error", detail="Access denied")

    try:
        await google_calendar_service.exchange_code_and_save(
            db,
            user_id=oauth_state.user_id,
            code=code,
        )
    except GoogleCalendarError as exc:
        await db.rollback()
        logger.warning(
            "google_calendar_callback_failed", user_id=oauth_state.user_id, error=str(exc)
        )
        return _redirect_result(
            oauth_state.return_url,
            result="error",
            detail="Google Calendar connection failed",
        )
    return _redirect_result(oauth_state.return_url, result="connected")


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(db: DB, current_user: CurrentUser) -> None:
    await google_calendar_service.disconnect(db, user_id=current_user.id)


@router.get("/health", include_in_schema=False)
async def health(current_user: CurrentUser) -> dict[str, bool]:
    """Authenticated configuration probe; never exposes OAuth credentials."""
    if not google_calendar_service.google_calendar_configured():
        raise HTTPException(status_code=503, detail="Google Calendar OAuth is not configured")
    return {"configured": True}
