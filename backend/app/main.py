"""FastAPI application entry point."""

import math
import os
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import sentry_sdk
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.redirects import router as redirects_router
from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.api.webhooks.calcom import router as calcom_webhook_router
from app.api.webhooks.resend import router as resend_webhook_router
from app.api.webhooks.telnyx import router as telnyx_webhook_router
from app.core.config import settings
from app.core.request_id import sanitize_request_id
from app.core.telemetry import configure_tracing, instrument_app
from app.db.redis import close_redis
from app.db.session import engine
from app.websockets.voice_bridge import router as voice_bridge_router
from app.websockets.voice_test import router as voice_test_router
from app.workers import start_all_workers, stop_all_workers

logger = structlog.get_logger()


REQUEST_ID_HEADER = "x-request-id"


class RequestIDMiddleware:
    """Assign every HTTP request a correlation ID and propagate it everywhere.

    Behaviour:

    * Reads the inbound ``X-Request-ID`` header if present and well-formed,
      otherwise generates a fresh ULID.
    * Stores the ID on ``request.state.request_id`` so route handlers /
      dependencies can read it (see :mod:`app.api.deps`, which additionally
      binds ``workspace_id`` and ``user_id`` once auth resolves).
    * Binds the ID into structlog's contextvars so every log line emitted
      while handling this request automatically carries ``request_id=...``
      via the ``merge_contextvars`` processor configured in
      :mod:`app.core.logging`.
    * Writes the same ID back as the outbound ``X-Request-ID`` response
      header so clients can quote it when reporting bugs.

    Implemented as pure ASGI (no ``BaseHTTPMiddleware``) so we can mutate
    response headers without buffering the response body and so context-var
    binding happens in the same task that runs the endpoint.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract any inbound X-Request-ID header (case-insensitive per RFC 7230).
        inbound: str | None = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                try:
                    inbound = value.decode("latin-1")
                except UnicodeDecodeError:
                    inbound = None
                break

        request_id = sanitize_request_id(inbound)

        # Stash on ASGI scope so downstream code (Starlette's Request wrapper,
        # FastAPI dependencies) can read it via ``request.state.request_id``.
        scope.setdefault("state", {})
        if isinstance(scope["state"], dict):
            scope["state"]["request_id"] = request_id

        # Clear any inherited contextvars from a prior task on the same worker
        # before binding fresh ones for this request. Without the clear, a
        # long-lived worker can leak ``request_id`` / ``user_id`` from a prior
        # request into background logging that runs after the response is sent.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            # Drop contextvars so they don't leak into the next request on the
            # same task. The next request's middleware will re-bind anyway,
            # but unhandled background tasks spawned during this request
            # shouldn't inherit stale auth identifiers.
            structlog.contextvars.clear_contextvars()


class SecurityHeadersMiddleware:
    """Pure ASGI middleware to add security headers to all responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        connect_sources = [
            "'self'",
            "wss:",
            "https://api.openai.com",
            "https://api.telnyx.com",
            "https://api.elevenlabs.io",
        ]
        for origin in settings.cors_origins:
            if origin not in connect_sources:
                connect_sources.append(origin)
        if settings.frontend_url and settings.frontend_url not in connect_sources:
            connect_sources.append(settings.frontend_url)
        self._csp = "; ".join(
            [
                "default-src 'self'",
                "script-src 'self'",
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data: https:",
                "font-src 'self'",
                f"connect-src {' '.join(connect_sources)}",
                "frame-ancestors 'none'",
                "base-uri 'self'",
                "form-action 'self'",
            ]
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                headers["X-Frame-Options"] = "DENY"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
                headers["Content-Security-Policy"] = self._csp
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Minimum key material size in bytes. A 256-bit (32-byte) key is the recommended
# minimum for HMAC-SHA256 (used to sign JWTs) and Fernet. We require the key to:
#   1. Be at least 32 bytes long, AND
#   2. Carry enough Shannon entropy to rule out trivial repeats / dictionary words.
# A 64-char hex string from `openssl rand -hex 32` encodes 32 bytes of entropy
# in 64 visible bytes; we require at least half the theoretical maximum to allow
# for natural distribution skew while still rejecting strings like ``"a" * 64``.
_MIN_KEY_LENGTH_BYTES = 32
_MIN_KEY_ENTROPY_BITS = 128


def _shannon_entropy_bits(value: str) -> float:
    """Estimate total Shannon entropy of ``value`` in bits.

    Returns ``H * len(value_bytes)`` where ``H`` is the per-byte Shannon entropy
    in bits. A uniformly random 64-char hex string yields ~256 bits; a repetitive
    string like ``"a" * 64`` yields 0.
    """
    data = value.encode("utf-8")
    if not data:
        return 0.0
    counts: dict[int, int] = {}
    for byte in data:
        counts[byte] = counts.get(byte, 0) + 1
    length = len(data)
    entropy_per_byte = -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )
    return entropy_per_byte * length


def _validate_security_key(
    log: structlog.stdlib.BoundLogger,
    *,
    name: str,
    value: str,
    failure_detail: str,
) -> None:
    """Reject weak security-critical keys at startup.

    Refuses to boot when the configured key is shorter than
    :data:`_MIN_KEY_LENGTH_BYTES`, carries less than :data:`_MIN_KEY_ENTROPY_BITS`
    of Shannon entropy, or matches the legacy ``change-me-in-production``
    placeholder. The ``SECRET_KEY`` and ``ENCRYPTION_KEY`` fields on
    :class:`Settings` are already required (no defaults) with a pydantic-enforced
    minimum length, so the app refuses to boot without them regardless of the
    ``DEBUG`` flag — this check additionally rejects long-but-low-entropy values
    such as ``"a" * 64``.
    """
    if value == "change-me-in-production":
        log.error(
            f"insecure_{name.lower()}",
            severity="critical",
            message=f"Default placeholder {name} is not allowed",
        )
        raise RuntimeError(
            f"{name} must be set to a strong random value. "
            f"Default value 'change-me-in-production' is insecure. {failure_detail}"
        )

    byte_length = len(value.encode("utf-8"))
    if byte_length < _MIN_KEY_LENGTH_BYTES:
        log.error(
            f"short_{name.lower()}",
            severity="critical",
            byte_length=byte_length,
            required_bytes=_MIN_KEY_LENGTH_BYTES,
            message=f"{name} is shorter than {_MIN_KEY_LENGTH_BYTES} bytes",
        )
        raise RuntimeError(
            f"{name} must be at least {_MIN_KEY_LENGTH_BYTES} bytes "
            f"(got {byte_length}). Generate with `openssl rand -hex 32`. "
            f"{failure_detail}"
        )

    entropy_bits = _shannon_entropy_bits(value)
    if entropy_bits < _MIN_KEY_ENTROPY_BITS:
        log.error(
            f"weak_{name.lower()}",
            severity="critical",
            entropy_bits=round(entropy_bits, 2),
            required_entropy_bits=_MIN_KEY_ENTROPY_BITS,
            message=f"{name} has insufficient entropy",
        )
        raise RuntimeError(
            f"{name} has insufficient entropy "
            f"({entropy_bits:.1f} < {_MIN_KEY_ENTROPY_BITS} bits). "
            f"Use a CSPRNG-generated value, e.g. `openssl rand -hex 32`. "
            f"{failure_detail}"
        )


def _validate_startup_config() -> None:
    """Validate required configuration at startup.

    Checks for critical API keys and settings needed for application functionality.
    Logs warnings for incomplete integrations.
    """
    log = logger.bind(context="startup_validation")

    # Check required API keys
    if not settings.openai_api_key:
        log.warning("missing_openai_api_key", severity="critical")

    if not settings.telnyx_api_key:
        log.warning("missing_telnyx_api_key", severity="critical")

    # Check optional but important integrations
    if not settings.calcom_api_key:
        log.warning("missing_calcom_api_key", message="Cal.com appointments disabled")

    if not settings.elevenlabs_api_key:
        log.warning("missing_elevenlabs_api_key", message="ElevenLabs voice disabled")

    # Check Telnyx webhook configuration
    if not settings.telnyx_public_key and not settings.skip_webhook_verification:
        log.warning(
            "missing_telnyx_public_key",
            message="Telnyx webhook verification disabled",
        )

    # Check secret key security
    _validate_security_key(
        log,
        name="SECRET_KEY",
        value=settings.secret_key,
        failure_detail="Used to sign JWT access and refresh tokens.",
    )

    # Check encryption key security (used for Fernet encryption of tenant credentials)
    _validate_security_key(
        log,
        name="ENCRYPTION_KEY",
        value=settings.encryption_key,
        failure_detail=(
            "Used to encrypt tenant third-party credentials (Telnyx, OpenAI, "
            "FUB, Stripe). Leaving this default would expose every tenant's "
            "credentials if the database were dumped."
        ),
    )

    # Warn if webhook verification is disabled in non-debug mode
    if settings.skip_webhook_verification and not settings.debug:
        log.warning(
            "webhook_verification_disabled",
            severity="high",
            message="Webhook verification is disabled in production",
        )

    # Check database configuration
    if "localhost" in settings.database_url and not settings.debug:
        log.warning(
            "localhost_database_url",
            severity="high",
            message="Using localhost database URL in non-debug mode",
        )

    log.info("startup_validation_complete")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler.

    Sets ``app.state.ready`` to ``True`` only after configuration validation
    and worker startup both succeed. ``/readyz`` reads this flag and returns
    503 while it is ``False`` so orchestrators (Railway, Kubernetes) hold
    traffic on the previous container until this one finishes booting.
    """
    log = logger.bind(context="app_lifespan")
    log.info("Starting AI CRM backend...")

    # Default to not-ready so any in-flight readiness probe between process
    # start and lifespan completion returns 503. We never serve traffic with
    # this flag unset.
    app.state.ready = False

    # Validate configuration at startup
    _validate_startup_config()

    # Start all background workers
    await start_all_workers()

    # Only mark ready after both validation and worker startup succeed. If
    # either raises, ``ready`` stays ``False`` and the process exits before
    # serving traffic.
    app.state.ready = True
    log.info("startup_complete", ready=True)

    yield

    log.info("Shutting down AI CRM backend...")
    # Flip ready off immediately so /readyz reports 503 during drain.
    app.state.ready = False
    await stop_all_workers()
    await close_redis()
    # Dispose the SQLAlchemy engine so all pooled asyncpg connections are
    # closed cleanly. Without this, shutdown can leave half-open sockets that
    # Postgres only reaps after its ``idle_in_transaction_session_timeout``,
    # and asyncio raises "Event loop is closed" warnings as the loop tears
    # down underneath live connections.
    await engine.dispose()


# Initialize OpenTelemetry before app creation so auto-instrumentation can
# patch FastAPI / httpx / SQLAlchemy / Redis as they are imported and wired
# up below. No-op when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset.
configure_tracing(environment=settings.environment)

# Initialize Sentry before app creation so the SDK can patch ASGI/Starlette
# internals as FastAPI is constructed. No-op when ``sentry_dsn`` is unset.
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        environment=settings.environment,
        release=os.environ.get("RAILWAY_GIT_COMMIT_SHA"),
    )

app = FastAPI(
    title="AI CRM API",
    description="AI-powered CRM with voice agents, SMS campaigns, and Cal.com integration",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# OpenTelemetry instrumentation — must run after ``app`` is created but before
# any requests are served. No-op when tracing wasn't activated above.
instrument_app(app, engine)

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Request-ID middleware — runs outermost (added last) so the X-Request-ID
# response header is set on *every* response, including those produced by
# downstream middlewares (CORS preflight, security headers) and exception
# handlers. It also binds ``request_id`` into structlog contextvars before any
# route code runs, so every log line during the request is correlated.
app.add_middleware(RequestIDMiddleware)

# CORS middleware — allow configured origins plus Vercel preview deployments
_cors_origins = set(settings.cors_origins)
if settings.frontend_url:
    _cors_origins.add(settings.frontend_url)
_cors_origins_list = list(_cors_origins)

if settings.cors_allow_vercel_previews:
    # Build regex: exact origins OR Vercel preview deployments under this team only.
    # Lock to the project's team slug to prevent any other Vercel tenant from
    # hitting cookie-auth endpoints with allow_credentials=True. Vercel preview
    # URLs are of the form `<project>-<hash>-<team-slug>.vercel.app` for the
    # `ngrout70-6776s-projects` team.
    escaped = [re.escape(o) for o in _cors_origins_list]
    vercel_team_pattern = r"https://[a-z0-9-]+-ngrout70-6776s-projects\.vercel\.app"
    pattern = "^(?:" + "|".join(escaped) + "|" + vercel_team_pattern + ")$"
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=pattern,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
    )

# Include API router
app.include_router(api_router, prefix="/api/v1")

# Health, readiness, and version probes — mounted at root so orchestrators
# (Railway, Kubernetes) can hit them without an API prefix.
app.include_router(health_router, tags=["Health"])

# Public short-link redirects (no /api/v1 prefix — these are user-facing URLs)
app.include_router(redirects_router)

# Include webhook routers
app.include_router(telnyx_webhook_router, prefix="/webhooks/telnyx", tags=["webhooks"])
app.include_router(calcom_webhook_router, prefix="/webhooks/calcom", tags=["webhooks"])
app.include_router(resend_webhook_router, prefix="/webhooks/resend", tags=["webhooks"])

# Include WebSocket routers
app.include_router(voice_bridge_router, tags=["voice"])
app.include_router(voice_test_router, tags=["voice"])

# Mount static files for lead magnets and other assets
app.mount("/static", StaticFiles(directory="static"), name="static")


# --------------------------------------------------------------------------- #
# Prometheus metrics
# --------------------------------------------------------------------------- #
# Expose default HTTP metrics (request count/latency/size) at /metrics. The
# endpoint is gated behind a shared-secret bearer token (``settings.metrics_token``)
# so it can be reached by Prometheus/Grafana scrapers without being publicly
# scrapable. If ``metrics_token`` is unset the endpoint refuses all requests
# (returns 503) — we never want unauthenticated metrics in production because
# they leak request volumes, route names, and latency distributions.
def _verify_metrics_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    expected = settings.metrics_token
    if not expected:
        # Endpoint is mounted but disabled until a token is configured.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="metrics endpoint is not configured",
        )

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid metrics token",
            headers={"WWW-Authenticate": "Bearer"},
        )


Instrumentator().instrument(app).expose(
    app,
    endpoint="/metrics",
    include_in_schema=False,
    dependencies=[Depends(_verify_metrics_token)],
)


_STATUS_CODE_SLUGS: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "unprocessable_entity",
    429: "too_many_requests",
    500: "internal_server_error",
    502: "bad_gateway",
    503: "service_unavailable",
    504: "gateway_timeout",
}


def _error_payload_from_detail(status_code: int, detail: Any) -> dict[str, Any]:
    """Normalize an ``HTTPException.detail`` into ``ErrorResponse`` shape.

    - Preserves already-structured payloads (dicts with a ``code`` field).
    - Wraps plain strings / other types into ``{code, message}`` using a slug
      derived from the HTTP status code.

    The ``request_id`` field is attached separately by the response handler
    (it isn't known here at the payload-shape level).
    """
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        payload: dict[str, Any] = {
            "code": detail["code"],
            "message": str(detail.get("message", "")),
        }
        if "details" in detail:
            payload["details"] = detail["details"]
        return payload

    code = _STATUS_CODE_SLUGS.get(status_code, f"http_{status_code}")
    message = detail if isinstance(detail, str) else str(detail) if detail is not None else ""
    return {"code": code, "message": message}


def _request_id_for(request: Request) -> str:
    """Pull the correlation ID set by :class:`RequestIDMiddleware`.

    Falls back to the empty string when the middleware hasn't run (e.g. an
    error raised before middleware processing in a stripped-down test app),
    so the canonical ``{code, message, request_id}`` shape is always present.
    """
    return str(getattr(request.state, "request_id", "") or "")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return ``HTTPException``s in the canonical ``ErrorResponse`` shape."""
    payload = _error_payload_from_detail(exc.status_code, exc.detail)
    payload["request_id"] = _request_id_for(request)
    return JSONResponse(
        status_code=exc.status_code,
        content=payload,
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global handler for unhandled exceptions.

    Logs the full error internally but returns the canonical
    ``{code, message, request_id}`` envelope with a generic message so we
    don't leak internal details. The ``request_id`` lets a client quote a
    specific failure when filing a bug.
    """
    logger.error("unhandled_exception", exc_info=exc, path=str(request.url))
    sentry_sdk.capture_exception(exc)
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "Internal server error",
            "request_id": _request_id_for(request),
        },
    )
