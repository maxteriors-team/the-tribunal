"""OpenAI credential helpers.

Supports classic API keys, workspace OpenAI integrations, and OpenAI OAuth
access tokens with refresh-token renewal. Bearer values are intentionally never
logged by this module.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any

import httpx
import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.workspace import WorkspaceIntegration

logger = structlog.get_logger()

_OPENAI_INTEGRATION_TYPE = "openai"
_OPENAI_JWT_AUTH_CLAIM = "https://api.openai.com/auth"
_DEFAULT_OPENAI_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_DEFAULT_OPENAI_OAUTH_ORIGINATOR = "codex_cli_rs"
_DEFAULT_OPENAI_OAUTH_USER_AGENT = f"{_DEFAULT_OPENAI_OAUTH_ORIGINATOR}/0.0.0"
_OAUTH_REFRESH_WINDOW_MS = 5 * 60 * 1000


class OpenAICredentialError(RuntimeError):
    """Raised when usable OpenAI credentials cannot be resolved."""


@dataclass(frozen=True, slots=True)
class OpenAICredentialContext:
    """Resolved OpenAI credential metadata.

    ``bearer_token`` is the only secret-bearing field. Do not log or serialize the
    full object. Log only ``source``, ``account_id``, ``organization_id``, and
    ``expires_at`` when needed.
    """

    bearer_token: str
    source: str
    account_id: str | None = None
    organization_id: str | None = None
    expires_at: int | None = None
    is_oauth: bool = False
    refresh_token: str | None = None

    def openai_headers(self) -> dict[str, str]:
        """Build OpenAI API headers for this context."""
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        if self.organization_id:
            headers["OpenAI-Organization"] = self.organization_id
        if self.is_oauth:
            headers["originator"] = (
                settings.openai_oauth_originator or _DEFAULT_OPENAI_OAUTH_ORIGINATOR
            )
            headers["User-Agent"] = (
                settings.openai_oauth_user_agent or _DEFAULT_OPENAI_OAUTH_USER_AGENT
            )
            if self.account_id:
                headers["ChatGPT-Account-ID"] = self.account_id
        return headers


@dataclass(frozen=True, slots=True)
class _CredentialResolution:
    """Internal credential result plus optional encrypted-credential updates."""

    context: OpenAICredentialContext
    updated_credentials: dict[str, Any] | None = None


def get_openai_bearer_token() -> str:
    """Return the configured global OpenAI bearer token, preferring OAuth."""
    return settings.openai_oauth_access_token or settings.openai_api_key


def is_openai_configured() -> bool:
    """Return whether any global OpenAI credential is configured."""
    return bool(get_openai_bearer_token())


def create_openai_client() -> AsyncOpenAI:
    """Create an OpenAI SDK client with the configured global bearer token."""
    return AsyncOpenAI(api_key=get_openai_bearer_token())


async def create_workspace_openai_client(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> AsyncOpenAI:
    """Create an OpenAI client using the workspace credential, then env fallback."""
    return AsyncOpenAI(api_key=await get_workspace_openai_bearer_token(db, workspace_id))


async def get_workspace_openai_bearer_token(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> str:
    """Return the best OpenAI bearer token for a workspace-aware voice session."""
    return (await resolve_openai_credentials(db, workspace_id)).bearer_token


async def resolve_openai_credentials(
    db: AsyncSession | None = None,
    workspace_id: uuid.UUID | None = None,
    *,
    require_fresh: bool = True,
) -> OpenAICredentialContext:
    """Resolve the best OpenAI credential for a workspace-aware request.

    Resolution order:
    1. Active ``WorkspaceIntegration`` credentials for ``integration_type=openai``
       when ``db`` and ``workspace_id`` are provided.
    2. Global environment settings.

    Workspace credentials only fall back to environment credentials when the
    workspace integration is absent or contains no usable credential material. If
    a workspace explicitly configured expired OAuth credentials that cannot be
    refreshed, the resolver raises a generic credential error instead of silently
    using another workspace/global identity.
    """
    if db is not None and workspace_id is not None:
        integration = await _get_workspace_openai_integration(db, workspace_id)
        if integration is not None:
            resolution = await _resolve_credentials_dict(
                integration.credentials,
                source_base="workspace",
                require_fresh=require_fresh,
            )
            if resolution.updated_credentials is not None:
                integration.credentials = resolution.updated_credentials
                await db.commit()
                logger.info(
                    "openai_workspace_oauth_refreshed",
                    workspace_id=str(workspace_id),
                    source=resolution.context.source,
                    account_id=resolution.context.account_id,
                    expires_at=resolution.context.expires_at,
                )
            return resolution.context

    return await _resolve_env_credentials(require_fresh=require_fresh)


async def refresh_openai_oauth_token(refresh_token: str) -> OpenAICredentialContext:
    """Refresh an OpenAI OAuth access token using the Codex OAuth client."""
    client_id = settings.openai_oauth_client_id or _DEFAULT_OPENAI_OAUTH_CLIENT_ID

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                settings.openai_oauth_token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                },
            )
    except httpx.RequestError as exc:
        logger.warning(
            "openai_oauth_refresh_request_failed",
            error_type=type(exc).__name__,
        )
        raise OpenAICredentialError("OpenAI OAuth credentials could not be refreshed") from exc

    if response.status_code != httpx.codes.OK:
        logger.warning(
            "openai_oauth_refresh_rejected",
            status_code=response.status_code,
        )
        raise OpenAICredentialError("OpenAI OAuth credentials could not be refreshed")

    try:
        data = response.json()
    except ValueError as exc:
        raise OpenAICredentialError("OpenAI OAuth refresh returned invalid data") from exc

    access_token = _string_value(data.get("access_token"))
    refreshed_refresh_token = _string_value(data.get("refresh_token")) or refresh_token
    expires_in_seconds = _int_value(data.get("expires_in"))
    if not access_token or expires_in_seconds is None:
        raise OpenAICredentialError("OpenAI OAuth refresh returned incomplete data")

    expires_at = int(time.time() * 1000) + expires_in_seconds * 1000
    return OpenAICredentialContext(
        bearer_token=access_token,
        source="oauth_refresh",
        account_id=_extract_openai_account_id(access_token),
        expires_at=expires_at,
        is_oauth=True,
        refresh_token=refreshed_refresh_token,
    )


async def _get_workspace_openai_integration(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> WorkspaceIntegration | None:
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace_id,
            WorkspaceIntegration.integration_type == _OPENAI_INTEGRATION_TYPE,
            WorkspaceIntegration.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _resolve_env_credentials(*, require_fresh: bool) -> OpenAICredentialContext:
    credentials: dict[str, Any] = {
        "api_key": settings.openai_api_key,
        "access_token": settings.openai_oauth_access_token,
        "refresh_token": settings.openai_oauth_refresh_token,
        "expires_at": settings.openai_oauth_expires_at,
        "account_id": settings.openai_oauth_account_id,
    }
    resolution = await _resolve_credentials_dict(
        credentials,
        source_base="env",
        require_fresh=require_fresh,
    )
    return resolution.context


async def _resolve_credentials_dict(
    credentials: dict[str, Any],
    *,
    source_base: str,
    require_fresh: bool,
) -> _CredentialResolution:
    access_token = _string_value(credentials.get("access_token"))
    refresh_token = _string_value(credentials.get("refresh_token"))
    api_key = _string_value(credentials.get("api_key"))
    account_id = _string_value(credentials.get("account_id")) or _string_value(
        credentials.get("chatgpt_account_id")
    )
    organization_id = _string_value(credentials.get("organization_id"))
    expires_at = _coerce_expires_at(credentials.get("expires_at"))

    if access_token and not _requires_refresh(expires_at, require_fresh=require_fresh):
        return _CredentialResolution(
            OpenAICredentialContext(
                bearer_token=access_token,
                source=f"{source_base}_oauth",
                account_id=account_id or _extract_openai_account_id(access_token),
                organization_id=organization_id,
                expires_at=expires_at,
                is_oauth=True,
                refresh_token=refresh_token,
            )
        )

    if refresh_token is not None and (access_token is not None or not api_key):
        refreshed = await refresh_openai_oauth_token(refresh_token)
        context = replace(
            refreshed,
            source=f"{source_base}_oauth",
            account_id=refreshed.account_id or account_id,
            organization_id=organization_id,
        )
        updated_credentials = dict(credentials)
        updated_credentials["access_token"] = context.bearer_token
        updated_credentials["refresh_token"] = context.refresh_token or refresh_token
        updated_credentials["expires_at"] = context.expires_at
        if context.account_id:
            updated_credentials["account_id"] = context.account_id
        if organization_id:
            updated_credentials["organization_id"] = organization_id
        return _CredentialResolution(context, updated_credentials)

    if api_key:
        return _CredentialResolution(
            OpenAICredentialContext(
                bearer_token=api_key,
                source=f"{source_base}_api_key",
                organization_id=organization_id,
                is_oauth=False,
            )
        )

    if access_token and _requires_refresh(expires_at, require_fresh=require_fresh):
        raise OpenAICredentialError("OpenAI OAuth credentials are expired and cannot be refreshed")

    raise OpenAICredentialError("OpenAI credentials are not configured")


def _requires_refresh(expires_at: int | None, *, require_fresh: bool) -> bool:
    if not require_fresh or expires_at is None:
        return False
    return expires_at <= int(time.time() * 1000) + _OAUTH_REFRESH_WINDOW_MS


def _coerce_expires_at(value: object) -> int | None:
    int_value = _int_value(value)
    if int_value is None:
        return None
    if int_value < 20_000_000_000:
        return int_value * 1000
    return int_value


def _int_value(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if not isinstance(value, str):
        return None

    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(float(stripped))
    except ValueError:
        return None


def _string_value(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _extract_openai_account_id(access_token: str) -> str | None:
    payload = _decode_jwt_payload(access_token)
    auth_claim = payload.get(_OPENAI_JWT_AUTH_CLAIM)
    if isinstance(auth_claim, dict):
        account_id = auth_claim.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id

    account_id = payload.get("chatgpt_account_id")
    if isinstance(account_id, str) and account_id:
        return account_id
    return None


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}".encode("ascii"))
        parsed = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}
