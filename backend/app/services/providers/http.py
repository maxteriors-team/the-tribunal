"""Shared async HTTP client layer for external providers.

The helpers here centralize timeout defaults, retry/error classification,
and safe structured logging for first-party provider integrations. Service
modules should translate :class:`ProviderHTTPError` subclasses into any
legacy domain exceptions they expose publicly.
"""

from __future__ import annotations

import asyncio
import json as jsonlib
import random
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar, Literal, Self

import httpx
import structlog

HTTPMethod = Literal["DELETE", "GET", "PATCH", "POST", "PUT"]
JSONValue = dict[str, Any] | list[Any] | str | int | float | bool | None

REDACTED = "[REDACTED]"
_PROVIDER_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_PROVIDER_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "cal-api-key",
        "telnyx-api-key",
    }
)
_SENSITIVE_BODY_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "password",
    }
)
_PROVIDER_ERROR_DETAIL_LIMIT = 500
_BEARER_TOKEN_RE = re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]+")
_SECRET_PAIR_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password)"
    r"(\s*[:=]\s*)"
    r"([^\s,&;]+)"
)


@dataclass(frozen=True, slots=True)
class ProviderRetryPolicy:
    """Retry settings for provider HTTP calls."""

    max_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    retry_status_codes: frozenset[int] = field(default_factory=lambda: frozenset({429}))
    retry_status_ranges: tuple[tuple[int, int], ...] = ((500, 599),)

    def should_retry_status(self, status_code: int) -> bool:
        """Return True when ``status_code`` should be retried if attempts remain."""
        if status_code in self.retry_status_codes:
            return True
        return any(start <= status_code <= end for start, end in self.retry_status_ranges)

    def next_backoff(self, current: float) -> float:
        """Return the next exponential backoff with jitter, capped at the policy max."""
        jittered = current + random.uniform(0, current)
        return min(jittered, self.max_backoff_seconds)


@dataclass(frozen=True, slots=True)
class ProviderErrorInfo:
    """Typed provider error metadata safe to log or surface internally."""

    provider: str
    status_code: int | None
    code: str
    message: str
    retryable: bool
    request_method: str
    request_url: str
    response_body: str | None = None


class ProviderHTTPError(Exception):
    """Base exception for failures returned by or while reaching a provider."""

    default_code: ClassVar[str] = "provider_error"

    def __init__(self, info: ProviderErrorInfo, cause: BaseException | None = None) -> None:
        self.info = info
        self.provider = info.provider
        self.status_code = info.status_code
        self.code = info.code or self.default_code
        self.message = info.message
        self.retryable = info.retryable
        self.request_method = info.request_method
        self.request_url = info.request_url
        self.response_body = info.response_body
        self.__cause__ = cause
        super().__init__(self.message)


class ProviderAuthError(ProviderHTTPError):
    """Provider rejected the configured credentials."""

    default_code: ClassVar[str] = "provider_auth_error"


class ProviderRateLimitError(ProviderHTTPError):
    """Provider returned a rate-limit response after retry attempts were exhausted."""

    default_code: ClassVar[str] = "provider_rate_limited"


class ProviderNotFoundError(ProviderHTTPError):
    """Provider resource was not found."""

    default_code: ClassVar[str] = "provider_not_found"


class ProviderResponseError(ProviderHTTPError):
    """Provider returned a terminal non-success response."""

    default_code: ClassVar[str] = "provider_response_error"


class ProviderTransportError(ProviderHTTPError):
    """Network or timeout failure while reaching a provider."""

    default_code: ClassVar[str] = "provider_transport_error"


class ProviderInvalidJSONError(ProviderHTTPError):
    """Provider returned a success response that was not valid JSON."""

    default_code: ClassVar[str] = "provider_invalid_json"


def provider_timeout() -> httpx.Timeout:
    """Return the shared provider timeout profile."""
    return _PROVIDER_TIMEOUT


def provider_limits() -> httpx.Limits:
    """Return the shared provider connection-pool limits."""
    return _PROVIDER_LIMITS


def parse_retry_after(value: str | None, fallback: float) -> float:
    """Parse a Retry-After header as delta-seconds or HTTP-date."""
    if value is None:
        return fallback

    stripped = value.strip()
    if not stripped:
        return fallback

    if stripped.isascii() and stripped.isdigit():
        return float(stripped)

    try:
        parsed_date = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError):
        return fallback

    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=UTC)

    return max(0.0, (parsed_date - datetime.now(UTC)).total_seconds())


def redact_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Return a redacted copy of HTTP headers safe for logs."""
    if not headers:
        return {}
    return {
        name: REDACTED if name.lower() in _SENSITIVE_HEADER_NAMES else value
        for name, value in sorted(headers.items(), key=lambda item: item[0].lower())
    }


def redact_json(value: JSONValue) -> JSONValue:
    """Redact known secret fields from JSON-like data without mutating it."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in sorted(value.items()):
            if key.lower() in _SENSITIVE_BODY_KEYS:
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_json(item)
        return redacted
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    return value


def response_error_message(response: httpx.Response) -> str:
    """Extract a concise provider error message from a response."""
    try:
        data = response.json()
    except (ValueError, TypeError):
        data = None

    if isinstance(data, dict):
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                detail = first.get("detail") or first.get("message") or first.get("title")
                if isinstance(detail, str) and detail:
                    return detail[:_PROVIDER_ERROR_DETAIL_LIMIT]
        error = data.get("error") or data.get("message")
        if isinstance(error, str) and error:
            return error[:_PROVIDER_ERROR_DETAIL_LIMIT]

    text = response.text.strip()
    if text:
        return text[:_PROVIDER_ERROR_DETAIL_LIMIT]
    return f"HTTP {response.status_code}"


def response_error_code(response: httpx.Response) -> str:
    """Extract a bounded provider error code from a response when present."""
    try:
        data = response.json()
    except (ValueError, TypeError):
        return f"http_{response.status_code}"

    if isinstance(data, dict):
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                code = first.get("code")
                if isinstance(code, str | int) and str(code):
                    return str(code)
        error_code = data.get("code") or data.get("error_code")
        if isinstance(error_code, str | int) and str(error_code):
            return str(error_code)

    return f"http_{response.status_code}"


def _redact_text(value: str) -> str:
    """Best-effort secret redaction for provider text snippets."""
    without_bearers = _BEARER_TOKEN_RE.sub(r"\1" + REDACTED, value)
    return _SECRET_PAIR_RE.sub(r"\1\2" + REDACTED, without_bearers)


def _response_body_for_error(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except (ValueError, TypeError):
        data = None

    if data is not None:
        redacted = redact_json(data)
        try:
            body = jsonlib.dumps(redacted, sort_keys=True)
        except (TypeError, ValueError):
            body = str(redacted)
        return body[:_PROVIDER_ERROR_DETAIL_LIMIT]

    text = response.text.strip()
    if not text:
        return None
    return _redact_text(text)[:_PROVIDER_ERROR_DETAIL_LIMIT]


def _request_url(request: httpx.Request) -> str:
    return str(request.url.copy_with(query=None))


def _response_error_class(status_code: int) -> type[ProviderHTTPError]:
    if status_code in {401, 403}:
        return ProviderAuthError
    if status_code == 404:
        return ProviderNotFoundError
    if status_code == 429:
        return ProviderRateLimitError
    return ProviderResponseError


class AsyncProviderHTTPClient:
    """Small async HTTP wrapper with shared provider policies."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        headers: Mapping[str, str] | None = None,
        retry_policy: ProviderRetryPolicy | None = None,
        logger: Any | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider = provider
        self.retry_policy = retry_policy or ProviderRetryPolicy()
        self.logger = (logger or structlog.get_logger()).bind(provider=provider)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            headers=dict(headers or {}),
            timeout=provider_timeout(),
            limits=provider_limits(),
            transport=transport,
        )

    @property
    def raw_client(self) -> httpx.AsyncClient:
        """Expose the underlying client for tests or gradual migrations."""
        return self._client

    @property
    def owns_client(self) -> bool:
        """Return whether this wrapper owns and closes the raw client."""
        return self._owns_client

    async def aclose(self) -> None:
        """Close the underlying HTTP client when this wrapper owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def request(
        self,
        method: HTTPMethod,
        url: str,
        *,
        expected_status_codes: set[int] | None = None,
        params: Mapping[str, str | int | bool | float | None] | None = None,
        json: JSONValue = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Send a provider HTTP request, retrying retryable failures."""
        attempts = max(1, self.retry_policy.max_attempts)
        backoff_seconds = self.retry_policy.initial_backoff_seconds
        request_headers = dict(headers or {})
        expected = expected_status_codes or set(range(200, 300))

        for attempt in range(1, attempts + 1):
            start = time.monotonic()
            try:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=request_headers or None,
                )
            except httpx.TransportError as exc:
                elapsed_ms = (time.monotonic() - start) * 1000.0
                if attempt < attempts:
                    sleep_for = backoff_seconds
                    self.logger.warning(
                        "provider_http_retry",
                        method=method,
                        url=url,
                        attempt=attempt,
                        max_attempts=attempts,
                        reason=type(exc).__name__,
                        retry_after_seconds=sleep_for,
                        elapsed_ms=round(elapsed_ms, 2),
                    )
                    await asyncio.sleep(sleep_for)
                    backoff_seconds = self.retry_policy.next_backoff(backoff_seconds)
                    continue
                raise self._transport_error(method, url, exc) from exc

            elapsed_ms = (time.monotonic() - start) * 1000.0
            status_code = response.status_code
            if status_code in expected:
                self.logger.info(
                    "provider_http_request_succeeded",
                    method=method,
                    url=_request_url(response.request),
                    status_code=status_code,
                    attempt=attempt,
                    elapsed_ms=round(elapsed_ms, 2),
                )
                return response

            retryable_status = self.retry_policy.should_retry_status(status_code)
            if attempt < attempts and retryable_status:
                sleep_for = self._sleep_for_response(response, backoff_seconds)
                self.logger.warning(
                    "provider_http_retry",
                    method=method,
                    url=_request_url(response.request),
                    status_code=status_code,
                    attempt=attempt,
                    max_attempts=attempts,
                    retry_after_seconds=sleep_for,
                    elapsed_ms=round(elapsed_ms, 2),
                    response_body=_response_body_for_error(response),
                )
                await asyncio.sleep(sleep_for)
                backoff_seconds = self.retry_policy.next_backoff(backoff_seconds)
                continue

            raise self._response_error(response, retryable=retryable_status)

        msg = "Provider HTTP retry loop ended unexpectedly"
        raise RuntimeError(msg)

    async def request_json(
        self,
        method: HTTPMethod,
        url: str,
        *,
        expected_status_codes: set[int] | None = None,
        params: Mapping[str, str | int | bool | float | None] | None = None,
        json: JSONValue = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send a provider request and parse a JSON object response."""
        response = await self.request(
            method,
            url,
            expected_status_codes=expected_status_codes,
            params=params,
            json=json,
            headers=headers,
        )
        try:
            data = response.json()
        except (ValueError, TypeError) as exc:
            raise self._invalid_json_error(response, exc) from exc
        if not isinstance(data, dict):
            info = ProviderErrorInfo(
                provider=self.provider,
                status_code=response.status_code,
                code=ProviderInvalidJSONError.default_code,
                message="Provider returned a non-object JSON response",
                retryable=False,
                request_method=response.request.method,
                request_url=_request_url(response.request),
                response_body=_response_body_for_error(response),
            )
            raise ProviderInvalidJSONError(info)
        return data

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | bool | float | None] | None = None,
        headers: Mapping[str, str] | None = None,
        expected_status_codes: set[int] | None = None,
    ) -> dict[str, Any]:
        return await self.request_json(
            "GET",
            url,
            params=params,
            headers=headers,
            expected_status_codes=expected_status_codes,
        )

    async def post_json(
        self,
        url: str,
        *,
        json: JSONValue = None,
        headers: Mapping[str, str] | None = None,
        expected_status_codes: set[int] | None = None,
    ) -> dict[str, Any]:
        return await self.request_json(
            "POST",
            url,
            json=json,
            headers=headers,
            expected_status_codes=expected_status_codes,
        )

    async def patch(
        self,
        url: str,
        *,
        json: JSONValue = None,
        headers: Mapping[str, str] | None = None,
        expected_status_codes: set[int] | None = None,
    ) -> httpx.Response:
        return await self.request(
            "PATCH",
            url,
            json=json,
            headers=headers,
            expected_status_codes=expected_status_codes,
        )

    async def delete(
        self,
        url: str,
        *,
        json: JSONValue = None,
        headers: Mapping[str, str] | None = None,
        expected_status_codes: set[int] | None = None,
    ) -> httpx.Response:
        return await self.request(
            "DELETE",
            url,
            json=json,
            headers=headers,
            expected_status_codes=expected_status_codes,
        )

    def _sleep_for_response(self, response: httpx.Response, fallback: float) -> float:
        if response.status_code == 429:
            return parse_retry_after(response.headers.get("retry-after"), fallback=fallback)
        return fallback

    def _transport_error(
        self,
        method: str,
        url: str,
        exc: httpx.TransportError,
    ) -> ProviderTransportError:
        is_timeout = isinstance(exc, httpx.TimeoutException)
        info = ProviderErrorInfo(
            provider=self.provider,
            status_code=None,
            code="timeout" if is_timeout else ProviderTransportError.default_code,
            message=f"Provider request {'timed out' if is_timeout else 'failed'} after retries",
            retryable=True,
            request_method=method,
            request_url=url,
        )
        self.logger.warning(
            "provider_http_request_failed",
            method=method,
            url=url,
            error_type=type(exc).__name__,
            code=info.code,
            retryable=True,
        )
        return ProviderTransportError(info, cause=exc)

    def _response_error(self, response: httpx.Response, *, retryable: bool) -> ProviderHTTPError:
        error_cls = _response_error_class(response.status_code)
        info = ProviderErrorInfo(
            provider=self.provider,
            status_code=response.status_code,
            code=response_error_code(response),
            message=response_error_message(response),
            retryable=retryable,
            request_method=response.request.method,
            request_url=_request_url(response.request),
            response_body=_response_body_for_error(response),
        )
        self.logger.warning(
            "provider_http_request_failed",
            method=info.request_method,
            url=info.request_url,
            status_code=info.status_code,
            code=info.code,
            retryable=retryable,
            response_body=info.response_body,
        )
        return error_cls(info)

    def _invalid_json_error(
        self,
        response: httpx.Response,
        exc: BaseException,
    ) -> ProviderInvalidJSONError:
        info = ProviderErrorInfo(
            provider=self.provider,
            status_code=response.status_code,
            code=ProviderInvalidJSONError.default_code,
            message="Provider returned invalid JSON",
            retryable=False,
            request_method=response.request.method,
            request_url=_request_url(response.request),
            response_body=_response_body_for_error(response),
        )
        self.logger.warning(
            "provider_http_invalid_json",
            method=info.request_method,
            url=info.request_url,
            status_code=info.status_code,
            error=str(exc),
        )
        return ProviderInvalidJSONError(info, cause=exc)
