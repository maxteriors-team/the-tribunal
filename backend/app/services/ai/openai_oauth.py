"""OpenAI Codex OAuth helpers for ChatGPT subscription sign-in.

This module mirrors the Codex CLI browser login flow so a workspace can store a
ChatGPT-backed OpenAI OAuth session instead of a Platform API key. The default
client ID and localhost callback ports match OpenAI's published Codex CLI auth
flow; a custom client/redirect URI can be supplied through settings for hosted
or first-party deployments.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import InvalidToken, decrypt_json, encrypt_json
from app.models.workspace import WorkspaceIntegration, WorkspaceMembership

logger = structlog.get_logger()

DEFAULT_OPENAI_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_OAUTH_SCOPE = "openid profile email offline_access api.connectors.read api.connectors.invoke"
OPENAI_OAUTH_AUTH_CLAIM = "https://api.openai.com/auth"
OPENAI_INTEGRATION_TYPE = "openai"
OPENAI_OAUTH_STATE_TYPE = "openai_codex_oauth"
OPENAI_OAUTH_ORIGINATOR = "the-tribunal"
LOCAL_CALLBACK_HOST = "127.0.0.1"
LOCAL_CALLBACK_PATH = "/auth/callback"
LOCAL_CALLBACK_PORTS = (1455, 1457)
STATE_TTL_SECONDS = 10 * 60

_callback_server_lock = threading.Lock()
_callback_server: ThreadingHTTPServer | None = None
_callback_server_thread: threading.Thread | None = None
_callback_redirect_uri: str | None = None


class OpenAIOAuthError(RuntimeError):
    """Raised when the OpenAI OAuth flow cannot be completed."""


@dataclass(frozen=True, slots=True)
class OpenAIOAuthStart:
    """Authorization URL returned to the browser."""

    authorization_url: str
    redirect_uri: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class OpenAIOAuthStatus:
    """Safe OpenAI OAuth status for UI display."""

    connected: bool
    account_id: str | None = None
    email: str | None = None
    expires_at: int | None = None
    saved_at: str | None = None
    auth_method: str | None = None
    plan_type: str | None = None
    api_key_configured: bool = False
    realtime_model: str = settings.openai_realtime_model


@dataclass(frozen=True, slots=True)
class _OAuthState:
    """Verified OAuth callback state."""

    workspace_id: uuid.UUID
    user_id: int
    code_verifier: str
    redirect_uri: str
    client_id: str


def get_openai_oauth_client_id() -> str:
    """Return the configured OAuth client ID, defaulting to Codex CLI's public app."""
    configured = settings.openai_oauth_client_id.strip()
    return configured or DEFAULT_OPENAI_OAUTH_CLIENT_ID


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _now_ms() -> int:
    return int(time.time() * 1000)


def _encode_state(
    *,
    workspace_id: uuid.UUID,
    user_id: int,
    code_verifier: str,
    redirect_uri: str,
    client_id: str,
) -> tuple[str, int]:
    expires_at = datetime.now(UTC) + timedelta(seconds=STATE_TTL_SECONDS)
    expires_at_ms = int(expires_at.timestamp() * 1000)
    state = encrypt_json(
        {
            "typ": OPENAI_OAUTH_STATE_TYPE,
            "workspace_id": str(workspace_id),
            "user_id": user_id,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "nonce": secrets.token_urlsafe(16),
            "expires_at": expires_at_ms,
        }
    )
    return state, expires_at_ms


def _decode_state(state: str) -> _OAuthState:
    try:
        payload = decrypt_json(state)
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise OpenAIOAuthError("OpenAI sign-in state is invalid or expired") from exc

    if payload.get("typ") != OPENAI_OAUTH_STATE_TYPE:
        raise OpenAIOAuthError("OpenAI sign-in state is invalid")

    expires_at = _int_value(payload.get("expires_at"))
    if expires_at is None or expires_at <= _now_ms():
        raise OpenAIOAuthError("OpenAI sign-in state is expired")

    try:
        workspace_id = uuid.UUID(str(payload["workspace_id"]))
        user_id = int(payload["user_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenAIOAuthError("OpenAI sign-in state is incomplete") from exc

    code_verifier = _string_value(payload.get("code_verifier"))
    redirect_uri = _string_value(payload.get("redirect_uri"))
    client_id = _string_value(payload.get("client_id"))
    if code_verifier is None or redirect_uri is None or client_id is None:
        raise OpenAIOAuthError("OpenAI sign-in state is incomplete")

    return _OAuthState(
        workspace_id=workspace_id,
        user_id=user_id,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        client_id=client_id,
    )


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}".encode("ascii"))
        parsed = json.loads(decoded)
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _auth_claims(token: str) -> dict[str, Any]:
    payload = _decode_jwt_payload(token)
    auth = payload.get(OPENAI_OAUTH_AUTH_CLAIM)
    if isinstance(auth, dict):
        return auth
    return payload


def _extract_account_id(access_token: str, id_token: str | None = None) -> str | None:
    for token in (access_token, id_token):
        if not token:
            continue
        claims = _auth_claims(token)
        account_id = claims.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


def _extract_email(access_token: str, id_token: str | None = None) -> str | None:
    for token in (access_token, id_token):
        if not token:
            continue
        payload = _decode_jwt_payload(token)
        email = payload.get("email")
        if isinstance(email, str) and email:
            return email
        profile = payload.get("https://api.openai.com/profile")
        if isinstance(profile, dict):
            profile_email = profile.get("email")
            if isinstance(profile_email, str) and profile_email:
                return profile_email
    return None


def _extract_plan_type(access_token: str, id_token: str | None = None) -> str | None:
    for token in (access_token, id_token):
        if not token:
            continue
        plan_type = _auth_claims(token).get("chatgpt_plan_type")
        if isinstance(plan_type, str) and plan_type:
            return plan_type
    return None


def _configured_redirect_uri() -> str | None:
    redirect_uri = settings.openai_oauth_redirect_uri.strip()
    return redirect_uri or None


def _local_redirect_uri(port: int) -> str:
    return f"http://localhost:{port}{LOCAL_CALLBACK_PATH}"


def _safe_error_page(title: str, message: str) -> bytes:
    escaped_title = html.escape(title)
    escaped_message = html.escape(message)
    return f"""
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>{escaped_title}</title></head>
  <body style="font-family:system-ui,sans-serif;text-align:center;padding:80px 24px;">
    <h1>{escaped_title}</h1>
    <p>{escaped_message}</p>
    <p>You can close this tab and return to The Tribunal.</p>
  </body>
</html>
""".encode()


def _write_callback_response(
    handler: BaseHTTPRequestHandler,
    *,
    status_code: int,
    title: str,
    message: str,
) -> None:
    body = _safe_error_page(title, message)
    handler.send_response(status_code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class _OpenAICallbackHandler(BaseHTTPRequestHandler):
    """Small local callback server for Codex's localhost redirect URI."""

    server_version = "TribunalOpenAIOAuth/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug("openai_oauth_callback_http", message=format % args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != LOCAL_CALLBACK_PATH:
            _write_callback_response(
                self,
                status_code=404,
                title="Not found",
                message="This callback URL is only for OpenAI sign-in.",
            )
            return

        params = parse_qs(parsed.query)
        error = _first_query_value(params, "error")
        if error:
            description = _first_query_value(params, "error_description") or error
            _write_callback_response(
                self,
                status_code=400,
                title="OpenAI sign-in failed",
                message=description,
            )
            return

        code = _first_query_value(params, "code")
        state = _first_query_value(params, "state")
        if not code or not state:
            _write_callback_response(
                self,
                status_code=400,
                title="OpenAI sign-in failed",
                message="The callback did not include the expected authorization code.",
            )
            return

        redirect_uri = _callback_redirect_uri or _local_redirect_uri(LOCAL_CALLBACK_PORTS[0])
        try:
            asyncio.run(complete_openai_oauth_callback(code, state, redirect_uri))
        except Exception as exc:  # noqa: BLE001 - callback must convert all failures to HTML
            logger.warning(
                "openai_oauth_callback_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            _write_callback_response(
                self,
                status_code=400,
                title="OpenAI sign-in failed",
                message=str(exc),
            )
            return

        _write_callback_response(
            self,
            status_code=200,
            title="Signed in to The Tribunal",
            message="Your ChatGPT subscription is connected for OpenAI Realtime voice.",
        )


def _first_query_value(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def ensure_local_openai_oauth_callback_server() -> str:
    """Start the localhost OAuth callback server if needed and return its redirect URI."""
    global _callback_redirect_uri, _callback_server, _callback_server_thread

    with _callback_server_lock:
        if _callback_server is not None and _callback_redirect_uri is not None:
            return _callback_redirect_uri

        last_error: OSError | None = None
        for port in LOCAL_CALLBACK_PORTS:
            try:
                server = ThreadingHTTPServer((LOCAL_CALLBACK_HOST, port), _OpenAICallbackHandler)
            except OSError as exc:
                last_error = exc
                continue

            thread = threading.Thread(
                target=server.serve_forever,
                name=f"openai-oauth-callback-{port}",
                daemon=True,
            )
            thread.start()
            _callback_server = server
            _callback_server_thread = thread
            _callback_redirect_uri = _local_redirect_uri(port)
            logger.info("openai_oauth_callback_server_started", port=port)
            return _callback_redirect_uri

    detail = str(last_error) if last_error else "no localhost callback port available"
    raise OpenAIOAuthError(f"Could not start OpenAI sign-in callback server: {detail}")


def build_openai_oauth_start(workspace_id: uuid.UUID, user_id: int) -> OpenAIOAuthStart:
    """Build a Codex OAuth authorize URL for a workspace admin."""
    redirect_uri = _configured_redirect_uri() or ensure_local_openai_oauth_callback_server()
    code_verifier, code_challenge = _generate_pkce_pair()
    client_id = get_openai_oauth_client_id()
    state, expires_at = _encode_state(
        workspace_id=workspace_id,
        user_id=user_id,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        client_id=client_id,
    )
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": OPENAI_OAUTH_SCOPE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": OPENAI_OAUTH_ORIGINATOR,
        }
    )
    return OpenAIOAuthStart(
        authorization_url=f"{OPENAI_OAUTH_AUTHORIZE_URL}?{query}",
        redirect_uri=redirect_uri,
        expires_at=expires_at,
    )


async def complete_openai_oauth_callback(
    code: str,
    state: str,
    redirect_uri: str | None = None,
) -> OpenAIOAuthStatus:
    """Exchange an OAuth code and persist the resulting workspace credentials."""
    decoded_state = _decode_state(state)
    if redirect_uri is not None and redirect_uri != decoded_state.redirect_uri:
        raise OpenAIOAuthError("OpenAI sign-in redirect URI mismatch")

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            settings.openai_oauth_token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": decoded_state.client_id,
                "code": code,
                "redirect_uri": decoded_state.redirect_uri,
                "code_verifier": decoded_state.code_verifier,
            },
        )

    if response.status_code != httpx.codes.OK:
        logger.warning("openai_oauth_code_exchange_rejected", status_code=response.status_code)
        raise OpenAIOAuthError(f"OpenAI token exchange failed with status {response.status_code}")

    try:
        token_data = response.json()
    except ValueError as exc:
        raise OpenAIOAuthError("OpenAI token exchange returned invalid JSON") from exc

    access_token = _string_value(token_data.get("access_token"))
    refresh_token = _string_value(token_data.get("refresh_token"))
    id_token = _string_value(token_data.get("id_token"))
    expires_in = _int_value(token_data.get("expires_in"))
    if not access_token or not refresh_token or expires_in is None:
        raise OpenAIOAuthError("OpenAI token exchange returned incomplete credentials")

    account_id = _extract_account_id(access_token, id_token)
    if not account_id:
        raise OpenAIOAuthError("OpenAI sign-in did not return a ChatGPT account id")

    expires_at = _now_ms() + expires_in * 1000
    credentials: dict[str, Any] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "account_id": account_id,
        "auth_method": "chatgpt_subscription",
        "last_oauth_login_at": datetime.now(UTC).isoformat(),
    }
    if id_token:
        credentials["id_token"] = id_token
    email = _extract_email(access_token, id_token)
    if email:
        credentials["email"] = email
    plan_type = _extract_plan_type(access_token, id_token)
    if plan_type:
        credentials["chatgpt_plan_type"] = plan_type

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await _ensure_workspace_admin(db, decoded_state.workspace_id, decoded_state.user_id)
        await _upsert_openai_oauth_credentials(db, decoded_state.workspace_id, credentials)
        logger.info(
            "openai_oauth_connected",
            workspace_id=str(decoded_state.workspace_id),
            user_id=decoded_state.user_id,
            account_id=account_id,
            expires_at=expires_at,
        )
        return await get_openai_oauth_status(db, decoded_state.workspace_id)


async def _ensure_workspace_admin(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: int,
) -> None:
    result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None or membership.role not in ("owner", "admin"):
        raise OpenAIOAuthError("Admin access is required to connect OpenAI")


async def _get_openai_integration(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> WorkspaceIntegration | None:
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace_id,
            WorkspaceIntegration.integration_type == OPENAI_INTEGRATION_TYPE,
        )
    )
    return result.scalar_one_or_none()


async def _upsert_openai_oauth_credentials(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    oauth_credentials: dict[str, Any],
) -> None:
    integration = await _get_openai_integration(db, workspace_id)
    if integration is None:
        integration = WorkspaceIntegration(
            workspace_id=workspace_id,
            integration_type=OPENAI_INTEGRATION_TYPE,
            encrypted_credentials=encrypt_json(oauth_credentials),
            is_active=True,
        )
        db.add(integration)
    else:
        credentials = dict(integration.credentials)
        credentials.update(oauth_credentials)
        integration.credentials = credentials
        integration.is_active = True
    await db.commit()


async def get_openai_oauth_status(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> OpenAIOAuthStatus:
    """Return safe ChatGPT subscription login status for a workspace."""
    integration = await _get_openai_integration(db, workspace_id)
    if integration is None or not integration.is_active:
        return OpenAIOAuthStatus(connected=False)

    credentials = integration.credentials
    access_token = _string_value(credentials.get("access_token"))
    refresh_token = _string_value(credentials.get("refresh_token"))
    account_id = _string_value(credentials.get("account_id"))
    email = _string_value(credentials.get("email"))
    saved_at = _string_value(credentials.get("last_oauth_login_at"))
    auth_method = _string_value(credentials.get("auth_method"))
    plan_type = _string_value(credentials.get("chatgpt_plan_type"))
    expires_at = _int_value(credentials.get("expires_at"))

    return OpenAIOAuthStatus(
        connected=bool(access_token or refresh_token),
        account_id=account_id,
        email=email,
        expires_at=expires_at,
        saved_at=saved_at,
        auth_method=auth_method,
        plan_type=plan_type,
        api_key_configured=bool(_string_value(credentials.get("api_key"))),
    )


async def disconnect_openai_oauth(db: AsyncSession, workspace_id: uuid.UUID) -> OpenAIOAuthStatus:
    """Remove ChatGPT subscription credentials while preserving any API key fields."""
    integration = await _get_openai_integration(db, workspace_id)
    if integration is None:
        return OpenAIOAuthStatus(connected=False)

    credentials = dict(integration.credentials)
    for key in (
        "access_token",
        "refresh_token",
        "expires_at",
        "account_id",
        "email",
        "id_token",
        "auth_method",
        "chatgpt_plan_type",
        "last_oauth_login_at",
    ):
        credentials.pop(key, None)

    if _string_value(credentials.get("api_key")):
        integration.credentials = credentials
        await db.commit()
    else:
        await db.delete(integration)
        await db.commit()

    return OpenAIOAuthStatus(
        connected=False,
        api_key_configured=bool(_string_value(credentials.get("api_key"))),
    )


def _string_value(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _int_value(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(float(stripped))
        except ValueError:
            return None
    return None
