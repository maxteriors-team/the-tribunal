"""Authentication domain services."""

from app.services.auth.cookie_service import AuthCookieService
from app.services.auth.ip_rate_limit_service import (
    AUTH_RATE_LIMIT,
    AUTH_RATE_WINDOW_MINUTES,
    AuthIpRateLimitService,
)
from app.services.auth.password_change_service import PasswordChangeService
from app.services.auth.password_reset_service import PasswordResetService
from app.services.auth.token_rotation_service import AuthTokenPair, TokenRotationService
from app.services.auth.username_lockout_service import (
    LOGIN_FAILED_ENDPOINT,
    USERNAME_LOCKOUT_LIMIT,
    USERNAME_LOCKOUT_WINDOW_MINUTES,
    UsernameLockoutService,
    hash_username,
)
from app.services.auth.websocket_ticket_service import WebSocketTicketService

__all__ = [
    "AUTH_RATE_LIMIT",
    "AUTH_RATE_WINDOW_MINUTES",
    "LOGIN_FAILED_ENDPOINT",
    "USERNAME_LOCKOUT_LIMIT",
    "USERNAME_LOCKOUT_WINDOW_MINUTES",
    "AuthCookieService",
    "AuthIpRateLimitService",
    "AuthTokenPair",
    "PasswordChangeService",
    "PasswordResetService",
    "TokenRotationService",
    "UsernameLockoutService",
    "WebSocketTicketService",
    "hash_username",
]
