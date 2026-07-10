"""Per-workspace Google Calendar OAuth2 (authorization-code flow) + token refresh.

Cal.com uses one global API key; Google Calendar is OAuth2 per workspace. This
module builds the consent URL, exchanges the authorization code for tokens,
persists them encrypted on :class:`app.models.calendar_connection.CalendarConnection`,
and refreshes the access token on demand.

Security:
- Tokens are stored via ``encrypt_json`` (Fernet) and never logged.
- The OAuth ``state`` is an encrypted, expiring token (``encrypt_json``) carrying
  the workspace/user — only this backend can mint it, so the public callback can
  trust it without a session.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import decrypt_json, encrypt_json
from app.db.session import AsyncSessionLocal
from app.models.calendar_connection import CalendarConnection

logger = structlog.get_logger()

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

PROVIDER = "google"
STATE_TYPE = "google_calendar_oauth"
STATE_TTL_SECONDS = 600
# Refresh the access token when it expires within this window.
TOKEN_REFRESH_SKEW_SECONDS = 120
DEFAULT_CALENDAR_ID = "primary"


class GoogleOAuthError(Exception):
    """Google Calendar OAuth failure surfaced to the caller."""


@dataclass
class GoogleOAuthStart:
    """Consent-screen instructions returned to a workspace admin."""

    authorization_url: str
    redirect_uri: str
    expires_at: int


@dataclass
class GoogleCalendarStatus:
    """Safe (secret-free) connection status for a workspace."""

    connected: bool
    google_calendar_id: str | None = None
    token_expiry: str | None = None
    scopes: str | None = None
    saved_at: str | None = None
    client_configured: bool = False


@dataclass
class _OAuthState:
    workspace_id: uuid.UUID
    user_id: int


# ── Config helpers ──────────────────────────────────────────────────


def google_oauth_configured() -> bool:
    """Return whether the global Google OAuth client is configured."""
    return bool(
        settings.google_oauth_client_id
        and settings.google_oauth_client_secret
        and settings.google_oauth_redirect_uri
    )


def _require_client() -> tuple[str, str, str]:
    if not google_oauth_configured():
        raise GoogleOAuthError(
            "Google Calendar OAuth is not configured "
            "(set GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI)"
        )
    return (
        settings.google_oauth_client_id,
        settings.google_oauth_client_secret,
        settings.google_oauth_redirect_uri,
    )


def _scopes() -> str:
    return settings.google_oauth_scopes.strip()


# ── State encode/decode ─────────────────────────────────────────────


def _encode_state(*, workspace_id: uuid.UUID, user_id: int) -> tuple[str, int]:
    expires_at = datetime.now(UTC) + timedelta(seconds=STATE_TTL_SECONDS)
    expires_at_ms = int(expires_at.timestamp() * 1000)
    state = encrypt_json(
        {
            "typ": STATE_TYPE,
            "workspace_id": str(workspace_id),
            "user_id": user_id,
            "nonce": secrets.token_urlsafe(16),
            "expires_at": expires_at_ms,
        }
    )
    return state, expires_at_ms


def _decode_state(state: str) -> _OAuthState:
    try:
        payload: dict[str, Any] = decrypt_json(state)
    except Exception as exc:  # noqa: BLE001 - opaque token, treat all as invalid
        raise GoogleOAuthError("Google sign-in state is invalid or expired") from exc

    if payload.get("typ") != STATE_TYPE:
        raise GoogleOAuthError("Google sign-in state is invalid")

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, int) or _now_ms() > expires_at:
        raise GoogleOAuthError("Google sign-in state is expired")

    try:
        workspace_id = uuid.UUID(str(payload["workspace_id"]))
        user_id = int(payload["user_id"])
    except (KeyError, ValueError) as exc:
        raise GoogleOAuthError("Google sign-in state is incomplete") from exc

    return _OAuthState(workspace_id=workspace_id, user_id=user_id)


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


# ── Public flow ─────────────────────────────────────────────────────


def build_google_oauth_start(workspace_id: uuid.UUID, user_id: int) -> GoogleOAuthStart:
    """Build the Google consent URL for a workspace admin to connect their calendar."""
    client_id, _secret, redirect_uri = _require_client()
    state, expires_at = _encode_state(workspace_id=workspace_id, user_id=user_id)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": _scopes(),
            # offline + consent guarantees a refresh_token on (re)connect.
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return GoogleOAuthStart(
        authorization_url=f"{GOOGLE_AUTHORIZE_URL}?{query}",
        redirect_uri=redirect_uri,
        expires_at=expires_at,
    )


async def _exchange_code(code: str) -> dict[str, Any]:
    client_id, client_secret, redirect_uri = _require_client()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != httpx.codes.OK:
        logger.warning("google_oauth_token_exchange_failed", status_code=response.status_code)
        raise GoogleOAuthError("Google token exchange failed")
    return cast(dict[str, Any], response.json())


async def _refresh_token(refresh_token: str) -> dict[str, Any]:
    client_id, client_secret, _redirect_uri = _require_client()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != httpx.codes.OK:
        logger.warning("google_oauth_token_refresh_failed", status_code=response.status_code)
        raise GoogleOAuthError("Google token refresh failed")
    return cast(dict[str, Any], response.json())


def _expiry_from(expires_in: Any) -> datetime | None:
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return datetime.now(UTC) + timedelta(seconds=seconds)


async def get_connection(db: AsyncSession, workspace_id: uuid.UUID) -> CalendarConnection | None:
    """Return the workspace's active Google connection, if any."""
    result = await db.execute(
        select(CalendarConnection).where(
            CalendarConnection.workspace_id == workspace_id,
            CalendarConnection.provider == PROVIDER,
            CalendarConnection.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def complete_google_oauth_callback(*, code: str, state: str) -> GoogleCalendarStatus:
    """Exchange the callback code and persist encrypted tokens for the workspace."""
    decoded = _decode_state(state)
    token = await _exchange_code(code)

    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    if not access_token:
        raise GoogleOAuthError("Google did not return an access token")

    async with AsyncSessionLocal() as db:
        connection = await get_connection(db, decoded.workspace_id)
        # Also match an inactive row so reconnecting reuses the same record.
        if connection is None:
            existing = await db.execute(
                select(CalendarConnection).where(
                    CalendarConnection.workspace_id == decoded.workspace_id,
                    CalendarConnection.provider == PROVIDER,
                )
            )
            connection = existing.scalar_one_or_none()

        if connection is None:
            connection = CalendarConnection(
                workspace_id=decoded.workspace_id,
                provider=PROVIDER,
                google_calendar_id=DEFAULT_CALENDAR_ID,
            )
            db.add(connection)

        # Preserve an existing refresh token if Google omits it on reconnect.
        prior = connection.safe_credentials() or {}
        effective_refresh = refresh_token or prior.get("refresh_token")
        if not effective_refresh:
            raise GoogleOAuthError(
                "Google did not return a refresh token; reconnect with consent enabled"
            )

        connection.credentials = {
            "access_token": access_token,
            "refresh_token": effective_refresh,
        }
        connection.token_expiry = _expiry_from(token.get("expires_in"))
        connection.scopes = token.get("scope") or _scopes()
        if not connection.google_calendar_id:
            connection.google_calendar_id = DEFAULT_CALENDAR_ID
        connection.is_active = True

        await db.commit()
        await db.refresh(connection)
        logger.info(
            "google_calendar_connected",
            workspace_id=str(decoded.workspace_id),
            calendar_id=connection.google_calendar_id,
        )
        return _status_from(connection)


async def get_google_calendar_status(
    db: AsyncSession, workspace_id: uuid.UUID
) -> GoogleCalendarStatus:
    """Return the safe connection status for a workspace."""
    connection = await get_connection(db, workspace_id)
    if connection is None:
        return GoogleCalendarStatus(connected=False, client_configured=google_oauth_configured())
    return _status_from(connection)


async def disconnect_google_calendar(
    db: AsyncSession, workspace_id: uuid.UUID
) -> GoogleCalendarStatus:
    """Deactivate + best-effort revoke the workspace's Google connection."""
    connection = await get_connection(db, workspace_id)
    if connection is None:
        return GoogleCalendarStatus(connected=False, client_configured=google_oauth_configured())

    creds = connection.safe_credentials() or {}
    refresh_token = creds.get("refresh_token")

    connection.is_active = False
    connection.watch_channel_id = None
    connection.watch_resource_id = None
    connection.watch_expiration = None
    connection.sync_token = None
    await db.commit()

    if refresh_token:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(GOOGLE_REVOKE_URL, data={"token": refresh_token})
        except httpx.HTTPError:
            logger.warning("google_calendar_revoke_failed", workspace_id=str(workspace_id))

    return GoogleCalendarStatus(connected=False, client_configured=google_oauth_configured())


async def ensure_fresh_access_token(db: AsyncSession, connection: CalendarConnection) -> str:
    """Return a valid access token, refreshing (and persisting) it when near expiry.

    Raises ``GoogleOAuthError`` when no usable credential is available.
    """
    creds = connection.safe_credentials()
    if not creds:
        raise GoogleOAuthError("Google Calendar credentials are unreadable")

    access_token = creds.get("access_token")
    refresh_token = creds.get("refresh_token")

    if access_token and not _needs_refresh(connection.token_expiry):
        return str(access_token)

    if not refresh_token:
        raise GoogleOAuthError("Google Calendar connection has no refresh token")

    token = await _refresh_token(str(refresh_token))
    new_access = token.get("access_token")
    if not new_access:
        raise GoogleOAuthError("Google token refresh returned no access token")

    connection.credentials = {
        "access_token": new_access,
        # Google usually omits refresh_token on refresh; keep the existing one.
        "refresh_token": token.get("refresh_token") or refresh_token,
    }
    connection.token_expiry = _expiry_from(token.get("expires_in"))
    await db.commit()
    await db.refresh(connection)
    return str(new_access)


def make_token_provider(workspace_id: uuid.UUID) -> Callable[[], Awaitable[str]]:
    """Return a coroutine yielding a fresh access token for the workspace.

    Each call opens its own short-lived session, so the returned provider can
    safely outlive the factory that built it and always sees the latest tokens.
    """

    async def _provider() -> str:
        async with AsyncSessionLocal() as db:
            connection = await get_connection(db, workspace_id)
            if connection is None:
                raise GoogleOAuthError("No active Google Calendar connection for workspace")
            return await ensure_fresh_access_token(db, connection)

    return _provider


def _needs_refresh(token_expiry: datetime | None) -> bool:
    if token_expiry is None:
        return True
    skew = timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS)
    return datetime.now(UTC) >= (token_expiry - skew)


def _status_from(connection: CalendarConnection) -> GoogleCalendarStatus:
    return GoogleCalendarStatus(
        connected=connection.is_active,
        google_calendar_id=connection.google_calendar_id,
        token_expiry=connection.token_expiry.isoformat() if connection.token_expiry else None,
        scopes=connection.scopes,
        saved_at=connection.updated_at.isoformat() if connection.updated_at else None,
        client_configured=google_oauth_configured(),
    )
