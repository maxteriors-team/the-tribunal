"""Secure issuance and redemption of user-specific password-reset tokens."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.core.security import get_password_hash, revoke_all_user_refresh_tokens
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User

RESET_TOKEN_LIFETIME = timedelta(minutes=30)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PasswordResetService:
    """Issue opaque tokens and atomically consume them once."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def issue(self, email: str) -> tuple[User, str] | None:
        result = await self.db.execute(
            select(User).where(User.email_hash == hash_value(email)).with_for_update()
        )
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None

        await self.db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used.is_(False))
            .values(used=True)
        )
        token = secrets.token_urlsafe(32)
        self.db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_token_hash(token),
                expires_at=datetime.now(UTC) + RESET_TOKEN_LIFETIME,
            )
        )
        await self.db.commit()
        return user, token

    async def reset(self, token: str, new_password: str) -> bool:
        now = datetime.now(UTC)
        token_digest = _token_hash(token)
        candidate = (
            await self.db.execute(
                select(PasswordResetToken.user_id).where(
                    PasswordResetToken.token_hash == token_digest,
                    PasswordResetToken.used.is_(False),
                    PasswordResetToken.expires_at > now,
                )
            )
        ).scalar_one_or_none()
        if candidate is None:
            return False

        # Lock users before tokens everywhere, preventing reset/request deadlocks.
        user = (
            await self.db.execute(select(User).where(User.id == candidate).with_for_update())
        ).scalar_one_or_none()
        reset_token = (
            await self.db.execute(
                select(PasswordResetToken)
                .where(
                    PasswordResetToken.token_hash == token_digest,
                    PasswordResetToken.used.is_(False),
                    PasswordResetToken.expires_at > now,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if reset_token is None:
            await self.db.rollback()
            return False
        if user is None or not user.is_active:
            reset_token.used = True
            await self.db.commit()
            return False

        reset_token.used = True
        user.hashed_password = get_password_hash(new_password)
        user.must_change_password = False
        await revoke_all_user_refresh_tokens(self.db, user.id)
        await self.db.commit()
        return True
