"""Security utilities for authentication."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import argon2
import bcrypt as _bcrypt_lib
import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

_password_hasher = argon2.PasswordHasher()


def _is_bcrypt_hash(hashed_password: str) -> bool:
    """Check if a hash is in bcrypt format ($2b$, $2a$, $2y$)."""
    return hashed_password.startswith(("$2b$", "$2a$", "$2y$"))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password.

    Supports both Argon2id (current) and bcrypt (legacy) hashes.
    Use `password_needs_rehash` to check if the hash should be upgraded.
    """
    if _is_bcrypt_hash(hashed_password):
        return _bcrypt_lib.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (argon2.exceptions.VerifyMismatchError, argon2.exceptions.InvalidHashError):
        return False


def password_needs_rehash(hashed_password: str) -> bool:
    """Check if a password hash should be upgraded to Argon2id."""
    if _is_bcrypt_hash(hashed_password):
        return True
    return _password_hasher.check_needs_rehash(hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using Argon2id."""
    return _password_hasher.hash(password)


def _hash_jti(jti: str) -> str:
    """Create a SHA-256 hash of a JTI for storage."""
    return hashlib.sha256(jti.encode("utf-8")).hexdigest()


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt: str = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def create_refresh_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a JWT refresh token with a unique JTI claim."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    jti = str(uuid.uuid4())
    to_encode.update({"exp": expire, "type": "refresh", "jti": jti})
    encoded_jwt: str = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT access token."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        if payload.get("type") != "access":
            return None
        return payload
    except InvalidTokenError:
        return None


def decode_refresh_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT refresh token."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        # Verify it's a refresh token
        if payload.get("type") != "refresh":
            return None
        return payload
    except InvalidTokenError:
        return None


async def store_refresh_token(
    db: AsyncSession, user_id: int, jti: str, expires_at: datetime
) -> None:
    """Store a refresh token hash in the database."""
    from app.models.refresh_token import RefreshToken

    token_hash = _hash_jti(jti)
    record = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(record)


async def validate_refresh_token(db: AsyncSession, jti: str, user_id: int) -> bool:
    """Validate that a refresh token exists in the DB and is not revoked.

    Returns True if the token is valid, False otherwise.
    If a revoked token is reused, all tokens for that user are revoked
    (potential token theft detection).
    """
    from app.models.refresh_token import RefreshToken

    token_hash = _hash_jti(jti)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    record = result.scalar_one_or_none()

    if record is None:
        return False

    if record.revoked:
        # Revoked token reuse — potential theft. Revoke ALL tokens for this user.
        await revoke_all_user_refresh_tokens(db, user_id)
        return False

    return not record.expires_at < datetime.now(UTC)


async def revoke_refresh_token(db: AsyncSession, jti: str) -> None:
    """Revoke a single refresh token by its JTI."""
    from app.models.refresh_token import RefreshToken

    token_hash = _hash_jti(jti)
    await db.execute(
        update(RefreshToken).where(RefreshToken.token_hash == token_hash).values(revoked=True)
    )


async def revoke_all_user_refresh_tokens(db: AsyncSession, user_id: int) -> None:
    """Revoke all refresh tokens for a user (e.g. on password change)."""
    from app.models.refresh_token import RefreshToken

    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )


async def cleanup_expired_refresh_tokens(db: AsyncSession) -> int:
    """Delete expired refresh tokens. Returns number of rows deleted."""
    from sqlalchemy import delete as sa_delete

    from app.models.refresh_token import RefreshToken

    result = await db.execute(
        sa_delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(UTC))
    )
    return int(result.rowcount)  # type: ignore[attr-defined]
