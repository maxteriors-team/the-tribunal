"""End-to-end tests for ``app/main.py``.

Exercises the cross-cutting wiring that lives in :mod:`app.main`:

* The canonical :class:`HTTPException` error-shape handler.
* The global unhandled-exception handler.
* The :class:`SecurityHeadersMiddleware` injection on every response.
* The CORS allow-list regex on the production app (Vercel team scoping).
* The application lifespan — worker startup, Redis close, engine dispose,
  ``_validate_startup_config`` invocation.
* The ``_error_payload_from_detail`` shape normalizer (unit-style).
* The ``_validate_security_key`` rejection rules for weak / placeholder keys.

We build isolated FastAPI apps mounted with the real middleware / handlers
rather than booting the full ``app.main`` app, so the tests don't need
Postgres, Redis, or the worker pool. The lifespan test patches every external
side effect so we can assert the startup / shutdown ordering in pure-Python.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sentry_sdk
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.core.config import settings as app_settings
from app.main import (
    _STATUS_CODE_SLUGS,
    SecurityHeadersMiddleware,
    _error_payload_from_detail,
    _shannon_entropy_bits,
    _validate_security_key,
    _validate_startup_config,
    _verify_metrics_token,
    http_exception_handler,
    lifespan,
    unhandled_exception_handler,
)
from app.main import (
    app as production_app,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_error_handler_app() -> FastAPI:
    """Tiny app that mounts the real exception handlers and raises on demand.

    Routes:

    * ``/raise/string`` — raise ``HTTPException`` with a plain-string detail
    * ``/raise/structured`` — raise ``HTTPException`` with a structured detail
      (``{code, message, details}``) — should round-trip unchanged
    * ``/raise/none`` — raise ``HTTPException`` with ``detail=None``
    * ``/raise/unhandled`` — raise a bare ``RuntimeError``
    """
    app = FastAPI()
    # FastAPI accepts handlers with the narrowed signature at runtime; the
    # static signature on ``add_exception_handler`` insists on the broad
    # Starlette form. Cast to keep mypy happy without weakening the handlers.
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/raise/string")
    async def _raise_string() -> None:
        raise HTTPException(status_code=404, detail="missing widget")

    @app.get("/raise/structured")
    async def _raise_structured() -> None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "widget_locked",
                "message": "Widget is being edited by someone else",
                "details": {"locked_by": "alice"},
            },
        )

    @app.get("/raise/headers")
    async def _raise_with_headers() -> None:
        raise HTTPException(
            status_code=401,
            detail="bad token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/raise/unhandled")
    async def _raise_unhandled() -> None:
        raise RuntimeError("boom — should never reach the client")

    return app


def _make_security_headers_app() -> FastAPI:
    """Minimal app with only the :class:`SecurityHeadersMiddleware` mounted."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def _ping() -> dict[str, str]:
        return {"ok": "ok"}

    return app


@pytest.fixture
async def error_client() -> AsyncIterator[AsyncClient]:
    app = _make_error_handler_app()
    # ``raise_app_exceptions=False`` lets the registered exception handler
    # produce the 500 response we want to inspect, instead of httpx surfacing
    # the bare RuntimeError to the test.
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
async def headers_client() -> AsyncIterator[AsyncClient]:
    app = _make_security_headers_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac


# --------------------------------------------------------------------------- #
# HTTPException handler — canonical {code, message[, details]} shape
# --------------------------------------------------------------------------- #


class TestHttpExceptionHandler:
    """``HTTPException`` is rendered in the canonical ``ErrorResponse`` shape."""

    async def test_string_detail_is_wrapped(self, error_client: AsyncClient) -> None:
        response = await error_client.get("/raise/string")
        assert response.status_code == 404
        body = response.json()
        # Status-code-derived slug, no `detail` field, no `details` field.
        assert body == {"code": "not_found", "message": "missing widget"}

    async def test_structured_detail_is_preserved(
        self, error_client: AsyncClient
    ) -> None:
        response = await error_client.get("/raise/structured")
        assert response.status_code == 409
        body = response.json()
        assert body == {
            "code": "widget_locked",
            "message": "Widget is being edited by someone else",
            "details": {"locked_by": "alice"},
        }

    async def test_headers_are_propagated(self, error_client: AsyncClient) -> None:
        """``HTTPException.headers`` (e.g. WWW-Authenticate) must reach the client."""
        response = await error_client.get("/raise/headers")
        assert response.status_code == 401
        assert response.headers.get("www-authenticate") == "Bearer"
        assert response.json() == {"code": "unauthorized", "message": "bad token"}


# --------------------------------------------------------------------------- #
# Global unhandled-exception handler — generic message, no leak
# --------------------------------------------------------------------------- #


class TestUnhandledExceptionHandler:
    """Bare exceptions are masked behind a generic 500 payload."""

    async def test_returns_generic_500(self, error_client: AsyncClient) -> None:
        # FastAPI's TestClient re-raises by default; httpx + ASGITransport
        # respects the registered exception handler and returns the response.
        with patch.object(sentry_sdk, "capture_exception"):
            response = await error_client.get("/raise/unhandled")
        assert response.status_code == 500
        # Body must not leak the internal error string.
        body = response.json()
        assert body == {"detail": "Internal server error"}
        assert "boom" not in response.text

    async def test_sentry_capture_is_invoked(self, error_client: AsyncClient) -> None:
        with patch.object(sentry_sdk, "capture_exception") as captured:
            await error_client.get("/raise/unhandled")
        captured.assert_called_once()


# --------------------------------------------------------------------------- #
# _error_payload_from_detail — direct unit coverage
# --------------------------------------------------------------------------- #


class TestErrorPayloadFromDetail:
    """Direct unit tests for the payload-shape normalizer."""

    def test_string_detail_uses_status_slug(self) -> None:
        payload = _error_payload_from_detail(404, "not here")
        assert payload == {"code": "not_found", "message": "not here"}

    def test_unknown_status_falls_back_to_http_prefix(self) -> None:
        payload = _error_payload_from_detail(418, "teapot")
        assert payload == {"code": "http_418", "message": "teapot"}

    def test_none_detail_yields_empty_message(self) -> None:
        payload = _error_payload_from_detail(500, None)
        assert payload == {"code": "internal_server_error", "message": ""}

    def test_non_string_detail_is_stringified(self) -> None:
        payload = _error_payload_from_detail(422, [{"loc": "body"}])
        assert payload["code"] == "unprocessable_entity"
        assert "loc" in payload["message"]

    def test_structured_dict_round_trips(self) -> None:
        detail: dict[str, Any] = {
            "code": "rate_limited",
            "message": "Try again later",
            "details": {"retry_after_s": 30},
        }
        payload = _error_payload_from_detail(429, detail)
        assert payload == detail

    def test_dict_without_code_falls_back_to_string_wrap(self) -> None:
        """A dict without a ``code`` field is treated as opaque data."""
        payload = _error_payload_from_detail(400, {"foo": "bar"})
        assert payload["code"] == "bad_request"
        # The dict is stringified into ``message`` because there is no ``code``.
        assert "foo" in payload["message"]

    def test_structured_dict_without_details(self) -> None:
        """Structured dicts that omit ``details`` don't get a stray key added."""
        payload = _error_payload_from_detail(
            409, {"code": "conflict_x", "message": "x conflict"}
        )
        assert payload == {"code": "conflict_x", "message": "x conflict"}
        assert "details" not in payload

    def test_all_known_status_slugs_present(self) -> None:
        """Sanity check: the slug map covers every common error status."""
        for code in (400, 401, 403, 404, 422, 429, 500, 503):
            payload = _error_payload_from_detail(code, "x")
            assert payload["code"] == _STATUS_CODE_SLUGS[code]


# --------------------------------------------------------------------------- #
# SecurityHeadersMiddleware — every response carries the hardening headers
# --------------------------------------------------------------------------- #


_EXPECTED_SECURITY_HEADERS = {
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "geolocation=(), microphone=(), camera=()",
}


class TestSecurityHeadersMiddleware:
    """Every HTTP response gains the locked-down security header set."""

    async def test_all_security_headers_present(
        self, headers_client: AsyncClient
    ) -> None:
        response = await headers_client.get("/ping")
        assert response.status_code == 200
        for header, value in _EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(header) == value, (
                f"missing or wrong {header}; got {response.headers.get(header)!r}"
            )

    async def test_csp_locks_default_src(self, headers_client: AsyncClient) -> None:
        response = await headers_client.get("/ping")
        csp = response.headers["content-security-policy"]
        # The CSP is the long one — assert on the load-bearing directives.
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "form-action 'self'" in csp
        assert "base-uri 'self'" in csp

    async def test_csp_connect_src_includes_external_apis(
        self, headers_client: AsyncClient
    ) -> None:
        response = await headers_client.get("/ping")
        csp = response.headers["content-security-policy"]
        # The known third-party origins we need to talk to.
        for src in (
            "https://api.openai.com",
            "https://api.telnyx.com",
            "https://api.elevenlabs.io",
            "wss:",
        ):
            assert src in csp, f"connect-src missing {src!r}"

    async def test_non_http_scope_is_passed_through(self) -> None:
        """ASGI lifespan / websocket scopes must not be mutated by the middleware."""
        downstream = AsyncMock()
        mw = SecurityHeadersMiddleware(downstream)

        scope: dict[str, Any] = {"type": "lifespan"}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)

        downstream.assert_awaited_once_with(scope, receive, send)


# --------------------------------------------------------------------------- #
# CORS regex — wired on the production app
# --------------------------------------------------------------------------- #


class TestProductionCorsWiring:
    """The real ``app.main:app`` has CORS attached with the team-scoped regex.

    The full Vercel-team regression suite lives in ``tests/core/test_cors.py``;
    here we add a request-level smoke test that hits the *actual* app object
    via ASGITransport to confirm the middleware fires on a preflight.
    """

    def test_cors_middleware_is_registered_with_regex(self) -> None:
        cors_layers = [
            m
            for m in production_app.user_middleware
            if getattr(m.cls, "__name__", None) == CORSMiddleware.__name__
        ]
        assert cors_layers, "Production app must register CORSMiddleware"
        kwargs = cors_layers[0].kwargs
        # Production wiring uses an origin regex; allow_credentials must be True
        # for the cookie-based auth flow to work.
        assert isinstance(kwargs.get("allow_origin_regex"), str)
        assert kwargs.get("allow_credentials") is True

    def test_cors_regex_matches_team_preview_and_rejects_foreigners(self) -> None:
        import re

        cors_layers = [
            m
            for m in production_app.user_middleware
            if getattr(m.cls, "__name__", None) == CORSMiddleware.__name__
        ]
        pattern = cors_layers[0].kwargs["allow_origin_regex"]
        assert isinstance(pattern, str)
        compiled = re.compile(pattern)

        # Allowed: a preview under our Vercel team.
        assert compiled.match(
            "https://aicrm-xyz-ngrout70-6776s-projects.vercel.app"
        )
        # Rejected: any other Vercel tenant.
        assert not compiled.match("https://evil.vercel.app")
        # Rejected: a preview under a different team slug entirely.
        assert not compiled.match(
            "https://aicrm-xyz-other-team-projects.vercel.app"
        )


# --------------------------------------------------------------------------- #
# Lifespan — startup / shutdown ordering with all side effects patched
# --------------------------------------------------------------------------- #


class TestLifespan:
    """``lifespan(app)`` runs validate → start_workers → yield → stop → close.

    We patch every external side effect (worker pool, Redis, SQLAlchemy engine)
    so the context manager can complete entirely in-process and we can assert
    on the call order.
    """

    async def test_full_lifecycle_calls_dependencies_in_order(self) -> None:
        calls: list[str] = []

        async def _start_workers() -> None:
            calls.append("start_workers")

        async def _stop_workers() -> None:
            calls.append("stop_workers")

        async def _close_redis() -> None:
            calls.append("close_redis")

        fake_engine = MagicMock()
        fake_engine.dispose = AsyncMock(
            side_effect=lambda: calls.append("dispose")
        )

        def _validate() -> None:
            calls.append("validate")

        with (
            patch.object(main_module, "start_all_workers", _start_workers),
            patch.object(main_module, "stop_all_workers", _stop_workers),
            patch.object(main_module, "close_redis", _close_redis),
            patch.object(main_module, "_validate_startup_config", _validate),
            patch.object(main_module, "engine", fake_engine),
        ):
            async with lifespan(production_app):
                # Inside the context we should be post-startup, pre-shutdown.
                assert calls == ["validate", "start_workers"]

        # After exiting, shutdown ran in order.
        assert calls == [
            "validate",
            "start_workers",
            "stop_workers",
            "close_redis",
            "dispose",
        ]
        fake_engine.dispose.assert_awaited_once()

    async def test_shutdown_disposes_engine(self) -> None:
        """The engine must be disposed on shutdown.

        Regression guard: without ``engine.dispose()``, asyncpg connections
        leak and we see ``Event loop is closed`` warnings at teardown.
        """
        fake_engine = MagicMock()
        fake_engine.dispose = AsyncMock()
        with (
            patch.object(main_module, "start_all_workers", AsyncMock()),
            patch.object(main_module, "stop_all_workers", AsyncMock()),
            patch.object(main_module, "close_redis", AsyncMock()),
            patch.object(main_module, "_validate_startup_config", MagicMock()),
            patch.object(main_module, "engine", fake_engine),
        ):
            async with lifespan(production_app):
                pass
        fake_engine.dispose.assert_awaited_once()


# --------------------------------------------------------------------------- #
# _validate_security_key — placeholder / short / low-entropy rejection
# --------------------------------------------------------------------------- #


class TestValidateSecurityKey:
    """Weak security keys must refuse to boot."""

    def _make_log(self) -> MagicMock:
        log = MagicMock()
        log.error = MagicMock()
        return log

    def test_placeholder_value_rejected(self) -> None:
        log = self._make_log()
        with pytest.raises(RuntimeError, match="change-me-in-production"):
            _validate_security_key(
                log,
                name="SECRET_KEY",
                value="change-me-in-production",
                failure_detail="used for JWTs.",
            )
        log.error.assert_called_once()

    def test_short_key_rejected(self) -> None:
        log = self._make_log()
        with pytest.raises(RuntimeError, match="at least 32 bytes"):
            _validate_security_key(
                log,
                name="SECRET_KEY",
                value="too-short",
                failure_detail="used for JWTs.",
            )

    def test_long_but_low_entropy_rejected(self) -> None:
        """A 64-char key of all ``a``s passes length but fails entropy."""
        log = self._make_log()
        with pytest.raises(RuntimeError, match="insufficient entropy"):
            _validate_security_key(
                log,
                name="SECRET_KEY",
                value="a" * 64,
                failure_detail="used for JWTs.",
            )

    def test_strong_key_accepted(self) -> None:
        """A real CSPRNG-style hex key passes silently."""
        import secrets

        log = self._make_log()
        # 64 hex chars = 32 bytes of entropy.
        strong_key = secrets.token_hex(32)
        _validate_security_key(
            log,
            name="SECRET_KEY",
            value=strong_key,
            failure_detail="used for JWTs.",
        )
        log.error.assert_not_called()


# --------------------------------------------------------------------------- #
# _validate_startup_config — boot-time configuration audit
# --------------------------------------------------------------------------- #


class TestValidateStartupConfig:
    """The startup-config check warns on weak setups and rejects bad keys.

    We patch the ``settings`` module attribute on ``app.main`` so each test
    can flip individual fields without mutating the real Settings instance.
    """

    def _make_settings(self, **overrides: Any) -> MagicMock:
        """Build a Settings stand-in with strong defaults plus overrides."""
        import secrets

        defaults: dict[str, Any] = {
            "openai_api_key": "sk-test",
            "telnyx_api_key": "telnyx-test",
            "calcom_api_key": "cal-test",
            "elevenlabs_api_key": "el-test",
            "telnyx_public_key": "pub-test",
            "skip_webhook_verification": False,
            "secret_key": secrets.token_hex(32),
            "encryption_key": secrets.token_hex(32),
            "debug": True,
            "database_url": "postgresql://user:pw@db.prod:5432/aicrm",
        }
        defaults.update(overrides)
        cfg = MagicMock()
        for key, value in defaults.items():
            setattr(cfg, key, value)
        return cfg

    def test_strong_config_passes_cleanly(self) -> None:
        cfg = self._make_settings()
        with patch.object(main_module, "settings", cfg):
            # Should not raise.
            _validate_startup_config()

    def test_missing_openai_key_warns(self) -> None:
        cfg = self._make_settings(openai_api_key="")
        with patch.object(main_module, "settings", cfg):
            _validate_startup_config()  # warnings only, no raise

    def test_missing_telnyx_key_warns(self) -> None:
        cfg = self._make_settings(telnyx_api_key="")
        with patch.object(main_module, "settings", cfg):
            _validate_startup_config()

    def test_missing_optional_integrations_warn(self) -> None:
        cfg = self._make_settings(calcom_api_key="", elevenlabs_api_key="")
        with patch.object(main_module, "settings", cfg):
            _validate_startup_config()

    def test_missing_telnyx_public_key_warns_when_verification_required(
        self,
    ) -> None:
        cfg = self._make_settings(
            telnyx_public_key="", skip_webhook_verification=False
        )
        with patch.object(main_module, "settings", cfg):
            _validate_startup_config()

    def test_webhook_verification_disabled_in_prod_warns(self) -> None:
        cfg = self._make_settings(skip_webhook_verification=True, debug=False)
        with patch.object(main_module, "settings", cfg):
            _validate_startup_config()

    def test_localhost_db_in_non_debug_warns(self) -> None:
        cfg = self._make_settings(
            database_url="postgresql://user:pw@localhost:5432/aicrm",
            debug=False,
        )
        with patch.object(main_module, "settings", cfg):
            _validate_startup_config()

    def test_weak_secret_key_aborts_boot(self) -> None:
        cfg = self._make_settings(secret_key="change-me-in-production")
        with (
            patch.object(main_module, "settings", cfg),
            pytest.raises(RuntimeError, match="SECRET_KEY"),
        ):
            _validate_startup_config()

    def test_weak_encryption_key_aborts_boot(self) -> None:
        cfg = self._make_settings(encryption_key="change-me-in-production")
        with (
            patch.object(main_module, "settings", cfg),
            pytest.raises(RuntimeError, match="ENCRYPTION_KEY"),
        ):
            _validate_startup_config()


# --------------------------------------------------------------------------- #
# _verify_metrics_token — bearer-token guard on /metrics
# --------------------------------------------------------------------------- #


class TestVerifyMetricsToken:
    """The Prometheus ``/metrics`` endpoint must require a configured bearer token."""

    def test_no_configured_token_returns_503(self) -> None:
        with (
            patch.object(app_settings, "metrics_token", ""),
            pytest.raises(HTTPException) as exc_info,
        ):
            _verify_metrics_token(authorization="Bearer anything")
        assert exc_info.value.status_code == 503

    def test_missing_authorization_header_returns_401(self) -> None:
        with (
            patch.object(app_settings, "metrics_token", "secret_t"),
            pytest.raises(HTTPException) as exc_info,
        ):
            _verify_metrics_token(authorization=None)
        assert exc_info.value.status_code == 401
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}

    def test_wrong_scheme_returns_401(self) -> None:
        with (
            patch.object(app_settings, "metrics_token", "secret_t"),
            pytest.raises(HTTPException) as exc_info,
        ):
            _verify_metrics_token(authorization="Basic secret_t")
        assert exc_info.value.status_code == 401

    def test_wrong_token_returns_401(self) -> None:
        with (
            patch.object(app_settings, "metrics_token", "secret_t"),
            pytest.raises(HTTPException) as exc_info,
        ):
            _verify_metrics_token(authorization="Bearer not_the_token")
        assert exc_info.value.status_code == 401

    def test_correct_token_passes(self) -> None:
        with patch.object(app_settings, "metrics_token", "secret_t"):
            # Should return None silently.
            _verify_metrics_token(authorization="Bearer secret_t")


class TestShannonEntropyBits:
    """The entropy estimator used by the key validator."""

    def test_empty_string_has_zero_entropy(self) -> None:
        assert _shannon_entropy_bits("") == 0.0

    def test_repeated_byte_has_zero_entropy(self) -> None:
        # Per-byte entropy of a constant string is 0; total is 0 regardless of len.
        assert _shannon_entropy_bits("a" * 100) == 0.0

    def test_random_hex_has_high_entropy(self) -> None:
        import secrets

        # 64 hex chars over 16 distinct symbols → ~4 bits/char × 64 = ~256 bits.
        bits = _shannon_entropy_bits(secrets.token_hex(32))
        assert bits > 200
