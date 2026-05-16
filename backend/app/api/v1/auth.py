"""Authentication endpoints."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.core.encryption import hash_value
from app.core.rate_limit_helpers import raise_rate_limited
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_password_hash,
    password_needs_rehash,
    revoke_all_user_refresh_tokens,
    revoke_refresh_token,
    store_refresh_token,
    validate_refresh_token,
    verify_password,
)
from app.core.utils import get_client_ip
from app.db.session import get_db
from app.models.auth_rate_limit import AuthRateLimit
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.schemas.user import (
    ChangePasswordRequest,
    Token,
    UserCreate,
    UserResponse,
    UserWithWorkspace,
)
from app.services.rate_limiting.auth_limiter import (
    enforce_change_password_rate_limit,
    enforce_ws_ticket_rate_limit,
)

router = APIRouter()

# Max auth attempts per IP per 15-minute window
_AUTH_RATE_LIMIT = 10
_AUTH_RATE_WINDOW_MINUTES = 15

# Max failed login attempts per *username* per 15-minute window. The IP-based
# counter above is insufficient on its own: a distributed attacker can rotate
# source IPs and brute-force a single account. Tracking failures by hashed
# username caps the total bad attempts an account can absorb regardless of how
# many source IPs the attacker controls.
_USERNAME_LOCKOUT_LIMIT = 10
_USERNAME_LOCKOUT_WINDOW_MINUTES = 15
_LOGIN_FAILED_ENDPOINT = "login_failed"


def _hash_username(username: str) -> str:
    """Return a SHA-256 hex digest of the lowercased username.

    Lowercased so case variations of the same email cannot bypass the lockout.
    Hashed so the rate-limit table never stores plaintext account identifiers.
    """
    return hashlib.sha256(username.strip().lower().encode("utf-8")).hexdigest()


_REFRESH_COOKIE_PATH = "/api/v1/auth"
_REFRESH_COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days
_ACCESS_COOKIE_NAME = "access_token"
# Access cookie is needed across the entire API surface, not just /auth.
_ACCESS_COOKIE_PATH = "/"


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set the refresh token as an httpOnly cookie on the response."""
    response.set_cookie(
        "refresh_token",
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=_REFRESH_COOKIE_MAX_AGE,
        path=_REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie."""
    response.delete_cookie(
        "refresh_token",
        path=_REFRESH_COOKIE_PATH,
    )


def _set_access_cookie(response: Response, token: str) -> None:
    """Set the access token as an httpOnly cookie on the response.

    Mirrors the refresh-token pattern: httpOnly + secure so JS in the browser
    cannot read or exfiltrate the token via XSS. ``samesite=lax`` blocks the
    cookie from being sent on most cross-site requests, which is the primary
    CSRF mitigation for state-changing endpoints.
    """
    response.set_cookie(
        _ACCESS_COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path=_ACCESS_COOKIE_PATH,
    )


def _clear_access_cookie(response: Response) -> None:
    """Clear the access token cookie."""
    response.delete_cookie(
        _ACCESS_COOKIE_NAME,
        path=_ACCESS_COOKIE_PATH,
    )


async def _check_auth_rate_limit(db: AsyncSession, client_ip: str, endpoint: str) -> None:
    """Check IP-based rate limit for authentication endpoints.

    Args:
        db: Database session
        client_ip: Client IP address
        endpoint: The endpoint being accessed (login, register, refresh)

    Raises:
        HTTPException: If rate limit exceeded
    """
    now = datetime.now(UTC)
    window_seconds = _AUTH_RATE_WINDOW_MINUTES * 60
    window_start = now - timedelta(seconds=window_seconds)

    # Pull the oldest in-window record alongside the count so we can compute
    # a precise ``Retry-After`` instead of a flat 15-minute default.
    count_result = await db.execute(
        select(func.count(), func.min(AuthRateLimit.created_at)).where(
            AuthRateLimit.client_ip == client_ip,
            AuthRateLimit.endpoint == endpoint,
            AuthRateLimit.created_at >= window_start,
        )
    )
    row = count_result.one()
    count = row[0] or 0
    oldest = row[1]

    if count >= _AUTH_RATE_LIMIT:
        retry_after = window_seconds
        if oldest is not None:
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=UTC)
            retry_after = max(
                1, int((oldest + timedelta(seconds=window_seconds) - now).total_seconds())
            )
        raise_rate_limited(
            retry_after,
            detail="Too many requests. Please try again later.",
        )

    # Record this attempt
    rate_limit_record = AuthRateLimit(client_ip=client_ip, endpoint=endpoint)
    db.add(rate_limit_record)
    await db.flush()


async def _check_username_lockout(db: AsyncSession, username: str) -> bool:
    """Return True iff the account is currently locked out.

    Counts ``login_failed`` rows for this username's hash inside the rolling
    window. The caller MUST treat a True result the same as a wrong-password
    response (generic 401) so a probe cannot tell whether the account exists.
    """
    window_start = datetime.now(UTC) - timedelta(minutes=_USERNAME_LOCKOUT_WINDOW_MINUTES)
    username_hash = _hash_username(username)

    count_result = await db.execute(
        select(func.count()).where(
            AuthRateLimit.username_hash == username_hash,
            AuthRateLimit.endpoint == _LOGIN_FAILED_ENDPOINT,
            AuthRateLimit.created_at >= window_start,
        )
    )
    count = count_result.scalar() or 0
    return count >= _USERNAME_LOCKOUT_LIMIT


async def _record_login_failure(db: AsyncSession, username: str, client_ip: str) -> None:
    """Record a failed login attempt against the username's hash."""
    db.add(
        AuthRateLimit(
            client_ip=client_ip,
            endpoint=_LOGIN_FAILED_ENDPOINT,
            username_hash=_hash_username(username),
        )
    )
    await db.flush()


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

    # Per-username lockout: if this account has accumulated too many recent
    # failures (across any source IPs), short-circuit with a generic 401 even
    # if the password is correct. This is the only check that defends against
    # a distributed brute-force rotating through many IPs.
    if await _check_username_lockout(db, form_data.username):
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Find user by email — lookup via the BLAKE2b hash column.
    result = await db.execute(select(User).where(User.email_hash == hash_value(form_data.username)))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(form_data.password, user.hashed_password):
        await _record_login_failure(db, form_data.username, client_ip)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Transparently upgrade legacy bcrypt hashes to Argon2id on successful login
    if password_needs_rehash(user.hashed_password):
        user.hashed_password = get_password_hash(form_data.password)
        await db.flush()

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    # Create access and refresh tokens
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )

    refresh_token_expires = timedelta(days=settings.refresh_token_expire_days)
    refresh_tok = create_refresh_token(
        data={"sub": str(user.id)},
        expires_delta=refresh_token_expires,
    )

    # Store refresh token hash in DB for server-side tracking
    refresh_payload = decode_refresh_token(refresh_tok)
    if refresh_payload and refresh_payload.get("jti"):
        await store_refresh_token(
            db,
            user_id=user.id,
            jti=refresh_payload["jti"],
            expires_at=datetime.fromtimestamp(refresh_payload["exp"], tz=UTC),
        )

    await db.commit()

    # Set both tokens as httpOnly cookies (JS cannot read them).
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_tok)

    return Token(access_token=access_token)


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Refresh access token using the refresh_token httpOnly cookie."""
    client_ip = get_client_ip(request, settings.trusted_proxies)
    await _check_auth_rate_limit(db, client_ip, "refresh")

    # Read refresh token from httpOnly cookie
    refresh_token_value = request.cookies.get("refresh_token")
    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode and validate refresh token
    payload = decode_refresh_token(refresh_token_value)
    if payload is None:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user ID from token
    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    try:
        user_id = int(user_id_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        ) from exc

    # Validate refresh token against DB (checks revocation + reuse detection)
    old_jti = payload.get("jti")
    if not old_jti or not await validate_refresh_token(db, old_jti, user_id):
        _clear_refresh_cookie(response)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify user exists and is active
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    # Revoke the old refresh token (rotation)
    await revoke_refresh_token(db, old_jti)

    # Create new access and refresh tokens
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )

    refresh_token_expires = timedelta(days=settings.refresh_token_expire_days)
    new_refresh_tok = create_refresh_token(
        data={"sub": str(user.id)},
        expires_delta=refresh_token_expires,
    )

    # Store new refresh token hash in DB
    new_payload = decode_refresh_token(new_refresh_tok)
    if new_payload and new_payload.get("jti"):
        await store_refresh_token(
            db,
            user_id=user.id,
            jti=new_payload["jti"],
            expires_at=datetime.fromtimestamp(new_payload["exp"], tz=UTC),
        )

    await db.commit()

    # Rotate both cookies on every refresh.
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, new_refresh_tok)

    return Token(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Logout by revoking the refresh token and clearing the cookie."""
    refresh_token_value = request.cookies.get("refresh_token")
    if refresh_token_value:
        payload = decode_refresh_token(refresh_token_value)
        if payload and payload.get("jti"):
            await revoke_refresh_token(db, payload["jti"])
            await db.commit()

    _clear_access_cookie(response)
    _clear_refresh_cookie(response)
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
    # Per-user rate limit: an authenticated-but-hijacked session shouldn't be
    # able to brute-force the current password. 5 attempts / hour is plenty
    # for a human and tight enough to make online brute force impractical.
    await enforce_change_password_rate_limit(current_user.id)

    # Verify current password
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Update password
    current_user.hashed_password = get_password_hash(body.new_password)

    # Revoke all refresh tokens for this user
    await revoke_all_user_refresh_tokens(db, current_user.id)

    await db.commit()

    # Clear the current session's auth cookies
    _clear_access_cookie(response)
    _clear_refresh_cookie(response)

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
    # Per-user rate limit on ticket minting. Each ticket opens a WS budget,
    # so a hijacked session could otherwise flood the WS layer. 30/min covers
    # normal reconnect storms (network blips, tab refreshes) comfortably.
    await enforce_ws_ticket_rate_limit(current_user.id)

    ticket = create_access_token(
        data={"sub": str(current_user.id)},
        expires_delta=timedelta(minutes=1),
    )
    return {"ticket": ticket}


@router.get("/me", response_model=UserWithWorkspace)
async def get_me(current_user: CurrentUser, db: DB) -> dict[str, Any]:
    """Get current user info with default workspace."""
    # Get default workspace (use first() in case multiple are marked as default)
    result = await db.execute(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.is_default.is_(True),
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
    }
