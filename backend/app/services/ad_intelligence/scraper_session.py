"""Token/cookie session layer for self-scraping the public Ad Library.

The public Ad Library website is powered by an internal endpoint
``POST https://www.facebook.com/ads/library/async/search_ads/`` that returns
``for (;;);``-prefixed JSON with ads under ``payload.results``. Calling it
requires a valid **LSD CSRF token** plus the session cookies the website sets,
which we harvest by loading the Ad Library page once and reusing them across
calls within a short TTL budget.

Two interchangeable strategies implement :class:`ScrapeSession`:

* :class:`TokenHttpSession` — lightweight, no browser. GETs the Ad Library page
  over ``httpx``, regexes the LSD token out of the HTML, keeps the cookie jar,
  and POSTs the async endpoints reusing them. Cheapest; most brittle to WAF /
  markup churn. Caches the harvested token+cookies in Redis (shared across
  replicas) with ``meta_scrape_session_ttl_seconds`` TTL and re-bootstraps once
  on 401/403.
* :class:`HeadlessSession` — heavier, lazily imported. Drives Playwright
  Chromium to the Ad Library page (a real browser produces valid tokens and a
  browser-grade TLS fingerprint), extracts the LSD token, then issues the async
  POSTs through the browser context's request API so cookies + fingerprint are
  reused. Survives token/markup churn better; needs the optional ``playwright``
  dependency.

Both honor an optional residential/ISP proxy (``meta_scrape_proxy_url``), which
is effectively required from datacenter IPs (Railway) where Meta serves
403/login challenges to datacenter egress.

Neither session decides *policy*: the compliance gate and rate limiting live in
the provider. This module only owns the token/cookie/proxy/transport lifecycle
and the ``for (;;);`` envelope decoding.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

import httpx
import structlog

from app.core.config import settings
from app.db.redis import get_redis
from app.services.lead_discovery.errors import (
    LeadDiscoveryAuthError,
    LeadDiscoveryProviderError,
    LeadDiscoveryRateLimitError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping

logger = structlog.get_logger()

AD_LIBRARY_URL = "https://www.facebook.com/ads/library/"
ASYNC_BASE = "https://www.facebook.com/ads/library/async"
# A current, desktop Chrome UA. The async endpoint rejects obviously-bot UAs.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_SESSION_CACHE_KEY = "ad_library:scrape:session"

# LSD CSRF token shapes seen in the Ad Library HTML, most specific first.
_LSD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r'\["LSD",\[\],\{"token":"([^"]+)"\}'),
    re.compile(r'"LSD",\[\],\{"token":"([^"]+)"\}'),
    re.compile(r'name="lsd"\s+value="([^"]+)"'),
    re.compile(r'"lsd":\{"token":"([^"]+)"\}'),
)
# Leading anti-JSON-hijacking guard the async endpoints prepend.
_FOR_LOOP_GUARD = re.compile(r"^\s*for\s*\(\s*;\s*;\s*\)\s*;")


# ---------------------------------------------------------------------------
# Pure envelope helpers (shared by both strategies; trivially unit-testable)
# ---------------------------------------------------------------------------


def extract_lsd(html: str) -> str | None:
    """Pull the LSD CSRF token out of the Ad Library page HTML, if present."""
    for pattern in _LSD_PATTERNS:
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None


def decode_async_payload(text: str) -> dict[str, Any]:
    """Strip the ``for (;;);`` guard and decode the async JSON envelope.

    Raises:
        LeadDiscoveryProviderError: when the body is not valid JSON after the
            guard is removed (markup/anti-bot HTML instead of JSON).
    """
    stripped = _FOR_LOOP_GUARD.sub("", text, count=1).strip()
    try:
        decoded: Any = json.loads(stripped)
    except ValueError as exc:
        raise LeadDiscoveryProviderError(
            "Ad Library async endpoint returned a non-JSON body "
            "(likely a login/challenge page; a residential proxy may be required)"
        ) from exc
    if not isinstance(decoded, dict):
        raise LeadDiscoveryProviderError("Ad Library async endpoint returned an unexpected shape")
    return decoded


@runtime_checkable
class ScrapeSession(Protocol):
    """Transport that POSTs the Ad Library async endpoints with a live token."""

    async def post(self, path: str, form: Mapping[str, Any]) -> dict[str, Any]:
        """POST ``form`` to ``async/<path>/`` and return the decoded envelope.

        Implementations inject the LSD token + ``__a=1`` and the harvested
        cookies, strip the ``for (;;);`` guard, and map transport failures to
        the discovery error hierarchy (401/403 -> auth, 429 -> rate-limit).
        """
        ...

    async def close(self) -> None:
        """Release any pooled resources (HTTP clients, browsers)."""
        ...


class TokenHttpSession:
    """Browser-free LSD-token + cookie session over ``httpx``."""

    strategy: ClassVar[str] = "token_http"

    def __init__(
        self,
        *,
        proxy_url: str | None = None,
        ttl_seconds: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the token/cookie HTTP session.

        Args:
            proxy_url: Optional residential/ISP proxy URL for all egress.
            ttl_seconds: Cross-process token cache TTL (Redis).
            client: Optional injected ``httpx.AsyncClient`` (tests/DI). When
                omitted the session owns a cookie-jar-bearing client.
        """
        resolved_proxy = proxy_url if proxy_url is not None else settings.meta_scrape_proxy_url
        self._proxy_url = resolved_proxy or None
        self._ttl_seconds = (
            ttl_seconds if ttl_seconds is not None else settings.meta_scrape_session_ttl_seconds
        )
        self._client = client
        self._owns_client = client is None
        # In-process cache of the harvested token (reused across paginated
        # calls within one search so we bootstrap at most once per search).
        self._lsd: str | None = None
        self._cookies: dict[str, str] = {}
        self._fetched_at: float = 0.0
        self._logger = logger.bind(component="meta_scrape_session", strategy=self.strategy)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.meta_ad_library_request_timeout_seconds),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                follow_redirects=True,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                proxy=self._proxy_url,
            )
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Token lifecycle
    # ------------------------------------------------------------------

    def _is_fresh(self) -> bool:
        return bool(self._lsd) and (time.monotonic() - self._fetched_at) < self._ttl_seconds

    async def _ensure_token(self) -> str:
        if self._is_fresh():
            return self._lsd or ""
        cached = await self._read_cache()
        if cached is not None:
            self._lsd, self._cookies, self._fetched_at = cached
            return self._lsd
        return await self._bootstrap()

    async def _bootstrap(self) -> str:
        """Load the Ad Library page, harvest the LSD token + cookies, cache them."""
        client = await self._get_client()
        try:
            response = await client.get(AD_LIBRARY_URL, params={"active_status": "all"})
        except httpx.TimeoutException as exc:
            raise LeadDiscoveryProviderError(f"Ad Library page load timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LeadDiscoveryProviderError(f"Ad Library page load failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise LeadDiscoveryAuthError(
                f"Ad Library page rejected the request (status {response.status_code}); "
                "a residential proxy is likely required from this IP"
            )
        if response.status_code != 200:
            raise LeadDiscoveryProviderError(
                f"Ad Library page load error (status {response.status_code})"
            )

        lsd = extract_lsd(response.text)
        if not lsd:
            raise LeadDiscoveryProviderError(
                "Could not extract an LSD token from the Ad Library page "
                "(markup changed or a challenge page was served)"
            )
        self._lsd = lsd
        self._cookies = {c.name: c.value for c in client.cookies.jar if c.value is not None}
        self._fetched_at = time.monotonic()
        await self._write_cache()
        self._logger.info("scrape_session_bootstrapped", cookie_count=len(self._cookies))
        return lsd

    async def _invalidate(self) -> None:
        self._lsd = None
        self._cookies = {}
        self._fetched_at = 0.0
        try:
            redis = await get_redis()
            await redis.delete(_SESSION_CACHE_KEY)
        except Exception as exc:  # noqa: BLE001 - cache is best-effort
            self._logger.debug("scrape_session_cache_clear_failed", error=type(exc).__name__)

    async def _read_cache(self) -> tuple[str, dict[str, str], float] | None:
        try:
            redis = await get_redis()
            raw = await redis.get(_SESSION_CACHE_KEY)
        except Exception as exc:  # noqa: BLE001 - fail open, bootstrap fresh
            self._logger.debug("scrape_session_cache_read_failed", error=type(exc).__name__)
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
            lsd = str(data["lsd"])
            cookies = {str(k): str(v) for k, v in dict(data.get("cookies", {})).items()}
        except (ValueError, KeyError, TypeError):
            return None
        # Re-prime the live client cookie jar so the cross-process token is usable.
        client = await self._get_client()
        for name, value in cookies.items():
            client.cookies.set(name, value, domain=".facebook.com")
        return lsd, cookies, time.monotonic()

    async def _write_cache(self) -> None:
        try:
            redis = await get_redis()
            await redis.setex(
                _SESSION_CACHE_KEY,
                max(1, self._ttl_seconds),
                json.dumps({"lsd": self._lsd, "cookies": self._cookies}),
            )
        except Exception as exc:  # noqa: BLE001 - cache is best-effort
            self._logger.debug("scrape_session_cache_write_failed", error=type(exc).__name__)

    # ------------------------------------------------------------------
    # Async POST
    # ------------------------------------------------------------------

    async def post(self, path: str, form: Mapping[str, Any]) -> dict[str, Any]:
        """POST to ``async/<path>/`` reusing the LSD token + cookies.

        Re-bootstraps the token exactly once on a 401/403 (stale token/cookies)
        before surfacing an auth error, so a single token expiry self-heals.
        """
        lsd = await self._ensure_token()
        try:
            return await self._post_once(path, form, lsd)
        except LeadDiscoveryAuthError:
            # Token/cookies likely went stale mid-budget; refresh once and retry.
            self._logger.info("scrape_session_reauth", path=path)
            await self._invalidate()
            lsd = await self._bootstrap()
            return await self._post_once(path, form, lsd)

    async def _post_once(self, path: str, form: Mapping[str, Any], lsd: str) -> dict[str, Any]:
        client = await self._get_client()
        body = {**form, "__a": "1", "lsd": lsd}
        headers = {
            "X-FB-LSD": lsd,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.facebook.com",
            "Referer": AD_LIBRARY_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        url = f"{ASYNC_BASE}/{path}/"
        try:
            response = await client.post(url, data=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise LeadDiscoveryProviderError(f"Ad Library async request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LeadDiscoveryProviderError(f"Ad Library async request failed: {exc}") from exc

        if response.status_code == 200:
            return decode_async_payload(response.text)
        if response.status_code == 429:
            self._logger.warning("scrape_rate_limited", status=response.status_code)
            raise LeadDiscoveryRateLimitError("Ad Library async endpoint throttled (429)")
        if response.status_code in (401, 403):
            self._logger.warning("scrape_auth_error", status=response.status_code)
            raise LeadDiscoveryAuthError(
                f"Ad Library async endpoint rejected the token (status {response.status_code})"
            )
        self._logger.warning("scrape_provider_error", status=response.status_code)
        raise LeadDiscoveryProviderError(
            f"Ad Library async endpoint error (status {response.status_code})"
        )


class HeadlessSession:
    """Playwright-Chromium LSD session (lazily imported, proxy-friendly)."""

    strategy: ClassVar[str] = "headless"

    def __init__(self, *, proxy_url: str | None = None) -> None:
        """Initialize the headless session.

        Args:
            proxy_url: Optional residential/ISP proxy URL for the browser.
        """
        self._proxy_url = (
            proxy_url if proxy_url is not None else settings.meta_scrape_proxy_url
        ) or None
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._lsd: str | None = None
        self._logger = logger.bind(component="meta_scrape_session", strategy=self.strategy)

    async def _ensure_context(self) -> Any:
        if self._context is not None:
            return self._context
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - optional heavy dep
            raise LeadDiscoveryProviderError(
                "Headless scrape strategy requires the optional 'playwright' "
                "dependency and a Chromium install (npx playwright install chromium). "
                "Use META_SCRAPE_STRATEGY=token_http for the browser-free path."
            ) from exc

        self._playwright = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": True}
        if self._proxy_url:
            launch_kwargs["proxy"] = {"server": self._proxy_url}
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(user_agent=DEFAULT_USER_AGENT)
        return self._context

    async def _ensure_token(self) -> str:
        if self._lsd:
            return self._lsd
        context = await self._ensure_context()
        page = await context.new_page()
        try:
            await page.goto(f"{AD_LIBRARY_URL}?active_status=all", wait_until="domcontentloaded")
            html = await page.content()
        finally:
            await page.close()
        lsd = extract_lsd(html)
        if not lsd:
            raise LeadDiscoveryProviderError(
                "Could not extract an LSD token from the headless Ad Library page"
            )
        self._lsd = lsd
        self._logger.info("scrape_session_bootstrapped")
        return lsd

    async def post(self, path: str, form: Mapping[str, Any]) -> dict[str, Any]:
        """POST through the browser context so cookies + fingerprint are reused."""
        lsd = await self._ensure_token()
        context = await self._ensure_context()
        body = {**{k: str(v) for k, v in form.items()}, "__a": "1", "lsd": lsd}
        try:
            response = await context.request.post(
                f"{ASYNC_BASE}/{path}/",
                form=body,
                headers={"X-FB-LSD": lsd, "Referer": AD_LIBRARY_URL},
            )
        except Exception as exc:  # noqa: BLE001 - playwright raises broad errors
            raise LeadDiscoveryProviderError(f"Headless async request failed: {exc}") from exc

        status = response.status
        if status == 200:
            return decode_async_payload(await response.text())
        if status == 429:
            raise LeadDiscoveryRateLimitError("Ad Library async endpoint throttled (429)")
        if status in (401, 403):
            # Drop the token so the next call re-bootstraps a fresh browser token.
            self._lsd = None
            raise LeadDiscoveryAuthError(
                f"Headless async endpoint rejected the token (status {status})"
            )
        raise LeadDiscoveryProviderError(f"Headless async endpoint error (status {status})")

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


def build_session(
    *,
    strategy: str | None = None,
    proxy_url: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> ScrapeSession:
    """Construct the configured scrape session.

    Args:
        strategy: ``token_http`` (default) or ``headless``. Falls back to
            ``meta_scrape_strategy``.
        proxy_url: Optional residential proxy URL.
        client: Optional injected ``httpx.AsyncClient`` (token_http only).
    """
    chosen = (strategy or settings.meta_scrape_strategy or "token_http").lower()
    if chosen == "headless":
        return HeadlessSession(proxy_url=proxy_url)
    return TokenHttpSession(proxy_url=proxy_url, client=client)
