"""Authentication endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.core.encryption import hash_value
from app.core.security import (
    get_password_hash,
    password_needs_rehash,
    verify_password,
)
from app.core.utils import get_client_ip
from app.db.session import get_db
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.schemas.user import (
    ChangePasswordRequest,
    Token,
    UserCreate,
    UserResponse,
    UserWithWorkspace,
)
from app.services.auth import (
    AUTH_RATE_LIMIT,
    AUTH_RATE_WINDOW_MINUTES,
    LOGIN_FAILED_ENDPOINT,
    USERNAME_LOCKOUT_LIMIT,
    USERNAME_LOCKOUT_WINDOW_MINUTES,
    AuthCookieService,
    AuthIpRateLimitService,
    PasswordChangeService,
    TokenRotationService,
    UsernameLockoutService,
    WebSocketTicketService,
    hash_username,
)
from app.services.rate_limiting.auth_limiter import (
    enforce_change_password_rate_limit,
    enforce_ws_ticket_rate_limit,
)
from app.services.workspaces import onboard_user_workspace

router = APIRouter()

# Backward-compatible constants/helpers imported by existing tests and workers.
_AUTH_RATE_LIMIT = AUTH_RATE_LIMIT
_AUTH_RATE_WINDOW_MINUTES = AUTH_RATE_WINDOW_MINUTES
_USERNAME_LOCKOUT_LIMIT = USERNAME_LOCKOUT_LIMIT
_USERNAME_LOCKOUT_WINDOW_MINUTES = USERNAME_LOCKOUT_WINDOW_MINUTES
_LOGIN_FAILED_ENDPOINT = LOGIN_FAILED_ENDPOINT

_cookie_service = AuthCookieService()


async def _check_auth_rate_limit(db: AsyncSession, client_ip: str, endpoint: str) -> None:
    """Check IP-based rate limit for authentication endpoints."""
    await AuthIpRateLimitService(db).enforce(client_ip=client_ip, endpoint=endpoint)


def _hash_username(username: str) -> str:
    """Return the hashed lockout key for a username."""
    return hash_username(username)


async def _check_username_lockout(db: AsyncSession, username: str) -> bool:
    """Return True iff the account is currently locked out."""
    return await UsernameLockoutService(db).is_locked_out(username)


async def _record_login_failure(db: AsyncSession, username: str, client_ip: str) -> None:
    """Record a failed login attempt against the username's hash."""
    await UsernameLockoutService(db).record_failure(username=username, client_ip=client_ip)


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set the refresh token as an httpOnly cookie on the response."""
    _cookie_service.set_refresh_cookie(response, token)


def _clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie."""
    _cookie_service.clear_refresh_cookie(response)


def _set_access_cookie(response: Response, token: str) -> None:
    """Set the access token as an httpOnly cookie on the response."""
    _cookie_service.set_access_cookie(response, token)


def _clear_access_cookie(response: Response) -> None:
    """Clear the access token cookie."""
    _cookie_service.clear_access_cookie(response)


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Register a new user."""
    client_ip = get_client_ip(request, settings.trusted_proxies)
    await _check_auth_rate_limit(db, client_ip, "register")

    # Check if email already exists — query the BLAKE2b lookup hash, not the
    # encrypted ``email`` column (Fernet ciphertext is non-deterministic so
    # equality matching there is impossible).
    email_hash = hash_value(user_in.email)
    result = await db.execute(select(User).where(User.email_hash == email_hash))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user — write encrypted value + lookup hash in lockstep.
    user = User(
        email=user_in.email,
        email_hash=email_hash,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
    )
    db.add(user)
    await db.flush()

    # Every new user must land in a usable default workspace; without one
    # /auth/me returns default_workspace_id=null and every workspace-scoped page
    # freezes on its loading skeleton (RF-001). An *invited* teammate lands in
    # the workspace that invited them — provisioning a personal workspace here
    # unconditionally is what used to strand invitees in an empty workspace of
    # their own instead of the team's.
    await onboard_user_workspace(db, user)

    await db.commit()
    await db.refresh(user)

    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Login and get access token.

    Both the access_token and refresh_token are set as httpOnly cookies so
    they are never exposed to JavaScript (XSS-resistant). The access_token is
    also returned in the JSON body for backward-compat callers (e.g. native
    integrations); browser clients should ignore it and rely on the cookie.
    """
    client_ip = get_client_ip(request, settings.trusted_proxies)
    await _check_auth_rate_limit(db, client_ip, "login")

    # Per-username lockout defends against distributed brute force. Locked-out
    # attempts return the same generic 401 as wrong credentials, and no extra
    # failure row is recorded so the rolling window can naturally clear.
    if await _check_username_lockout(db, form_data.username):
        await db.commit()
        raise _invalid_credentials()

    result = await db.execute(select(User).where(User.email_hash == hash_value(form_data.username)))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(form_data.password, user.hashed_password):
        await _record_login_failure(db, form_data.username, client_ip)
        await db.commit()
        raise _invalid_credentials()

    # Transparently upgrade legacy bcrypt hashes to Argon2id on successful login.
    if password_needs_rehash(user.hashed_password):
        user.hashed_password = get_password_hash(form_data.password)
        await db.flush()

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    # Belt-and-suspenders for accounts created before auto-provisioning (or any
    # path that left a user with zero memberships): heal on first login so they
    # never hit the infinite-skeleton dead end. Idempotent for everyone else —
    # in particular it never adds an existing member to a new workspace, so a
    # pending invitation still requires an explicit accept.
    await onboard_user_workspace(db, user)

    tokens = await TokenRotationService(db).issue_pair(user)
    await db.commit()

    _cookie_service.set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )

    return Token(access_token=tokens.access_token)


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Refresh access token using the refresh_token httpOnly cookie."""
    client_ip = get_client_ip(request, settings.trusted_proxies)
    await _check_auth_rate_limit(db, client_ip, "refresh")

    refresh_token_value = request.cookies.get("refresh_token")
    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        tokens = await TokenRotationService(db).rotate_refresh_token(refresh_token_value)
    except HTTPException as exc:
        is_invalid_refresh = (
            exc.status_code == status.HTTP_401_UNAUTHORIZED
            and exc.detail == "Invalid refresh token"
        )
        if is_invalid_refresh:
            _clear_refresh_cookie(response)
        raise

    await db.commit()

    _cookie_service.set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )

    return Token(access_token=tokens.access_token)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Logout by revoking the refresh token and clearing the cookie."""
    refresh_token_value = request.cookies.get("refresh_token")
    if refresh_token_value:
        revoked = await TokenRotationService(db).revoke_from_refresh_token(refresh_token_value)
        if revoked:
            await db.commit()

    _cookie_service.clear_auth_cookies(response)
    return {"message": "Logged out successfully"}


@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    body: ChangePasswordRequest,
    response: Response,
    current_user: CurrentUser,
    db: DB,
) -> dict[str, str]:
    """Change current user's password.

    Revokes all existing refresh tokens to force re-authentication
    on all devices.
    """
    service = PasswordChangeService(
        db,
        verify_password_func=verify_password,
        get_password_hash_func=get_password_hash,
        enforce_rate_limit_func=enforce_change_password_rate_limit,
    )
    await service.change_password(user=current_user, body=body)

    _cookie_service.clear_auth_cookies(response)
    return {"message": "Password updated successfully"}


@router.post("/ws-ticket", status_code=status.HTTP_200_OK)
async def issue_ws_ticket(current_user: CurrentUser) -> dict[str, str]:
    """Issue a short-lived ticket JWT for WebSocket authentication.

    WebSocket connections cannot read httpOnly cookies in JS to forward as a
    Bearer header, and cross-origin cookies on a WS handshake are unreliable.
    The browser exchanges its httpOnly access cookie (verified by
    ``CurrentUser`` here) for a small short-lived JWT that it appends as a
    query param on the WS URL. The ticket is single-purpose and expires in
    one minute, limiting the blast radius if it ever leaks via referer or
    server logs.
    """
    ticket = await WebSocketTicketService(
        enforce_rate_limit_func=enforce_ws_ticket_rate_limit,
    ).issue_ticket(current_user)
    return {"ticket": ticket}


@router.get("/me", response_model=UserWithWorkspace)
async def get_me(current_user: CurrentUser, db: DB) -> dict[str, Any]:
    """Get current user info with default workspace."""
    # Ordered, not just limited: with duplicate default rows (historical data —
    # see app.services.workspaces.membership.resolve_active_membership) an
    # unordered LIMIT 1 returns an arbitrary workspace, so the same user could be
    # handed a different default_workspace_id on consecutive requests. The
    # tie-break matches every other resolver.
    result = await db.execute(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.is_default.is_(True),
        )
        .order_by(
            WorkspaceMembership.created_at.asc(),
            WorkspaceMembership.id.asc(),
        )
        .limit(1)
    )
    membership = result.scalar_one_or_none()

    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at,
        "default_workspace_id": str(membership.workspace_id) if membership else None,
        "must_change_password": current_user.must_change_password,
    }
